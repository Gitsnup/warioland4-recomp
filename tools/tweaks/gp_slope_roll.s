.syntax unified
.cpu arm7tdmi
.thumb
@ Replacement body for the ground-pound-landing pose handler.
@
@ Original: func_8011898 (ROM 0x08011898) advances the landing animation for
@ poses 29 (GROUND_POUND_LANDING) and 30 (SUPER_GROUND_POUND_LANDING) and
@ returns a pose request when the animation completes (2 = STANDING).
@ This version probes the tile under Wario's feet first (func_806DAC0,
@ clip type 11 = slope) and, on a slope, returns 12 (STARTING_ROLL)
@ immediately, so a ground pound onto a slope flows straight into a roll.
@ Otherwise it reproduces the original animation stepper verbatim, including
@ the secondary (effect) animation driven through gUnk_3001930/sUnk_82E03BC.
@
@ Placed at ROM 0x08354408 (an all-zero gap between the sprite pose
@ graphics tables, see tools/wl4_tweak_gen.py for the placement contract).
@ The original handler entry becomes a branch through a repurposed pool
@ literal: the first instruction loads the helper address from its own
@ first pool word (0x080118A4, sUnk_82FC0D8 — dead in this path because
@ pose 29 selects kPrimGp via the second pool word instead) and bxes to it.
@   0x08011898: ldr r3, [pc, #8] / bx r3  (0x4B02, 0x4718)

gWarioData    = 0x03001898   @ struct WarioData (pose @+1, x @+0x12, y @+0x14)
gAnimCtx      = 0x03001931   @ unused here; kept for clarity
gLandingFxCtx = 0x03001930   @ gUnk_3001930: secondary anim ctx (step @+2, frame @+1)
kPrimGp       = 0x082FC0D8   @ primary anim table, poses 29/30
kPrimSuperGp  = 0x082FC0F0   @ primary anim table, other poses
kFxTable      = 0x082E03BC   @ secondary anim table (8-byte stride, dur @+4)

    push  {lr}
    ldr   r2, .Lpool_gwd
    ldrh  r0, [r2, #0x14]      @ y
    adds  r0, #1
    ldrh  r1, [r2, #0x12]      @ x
    @ Call func_806DAC0 through a local trampoline: a direct `bl 0x806DAC1`
    @ is a cross-section relocation that makes arm-none-eabi-ld synthesize a
    @ state-switch veneer AFTER this blob, which the ROM placement can't
    @ carry. `bl .Lcall_r3; bx r3` keeps everything self-contained.
    ldr   r3, .Lpool_probe
    bl    .Lcall_r3            @ func_806DAC0(y, x) -> clip type
    @ func_806DAC0 clobbers r2/r3 (it keeps its own map globals there), so
    @ reload gWarioData before touching Wario state again. The return packs
    @ (overridden<<16) | plainType, and every in-game caller (func_8010554,
    @ func_800FE58) branches on the HIGH halfword — do the same.
    ldr   r2, .Lpool_gwd
    asrs  r0, r0, #16
    lsls  r0, r0, #24
    lsrs  r0, r0, #24
    cmp   r0, #11              @ clip type 11 == slope tile
    bne   .Lkeep
    movs  r0, #12              @ WPOSE_NORMAL_STARTING_ROLL
    pop   {pc}

.Lkeep:
    ldrb  r0, [r2, #1]         @ current pose
    cmp   r0, #29
    bne   .Lsuper
    ldr   r3, .Lpool_prim
    b     .Lprim
.Lsuper:
    ldr   r3, .Lpool_prim2
.Lprim:
    @ Primary animation stepper (12-byte stride entries, duration @+8).
    ldrb  r0, [r2, #31]        @ step
    lsls  r1, r0, #1
    adds  r1, r1, r0
    lsls  r1, r1, #2
    adds  r1, r1, r3           @ entry = table + step*12
    ldrb  r0, [r2, #30]        @ frame counter
    ldrb  r1, [r1, #8]         @ duration
    cmp   r0, r1
    bcc   .Lsec                @ still animating -> run secondary effect
    movs  r0, #0
    strb  r0, [r2, #30]        @ frame = 0
    ldrb  r0, [r2, #31]
    adds  r0, #1
    strb  r0, [r2, #31]        @ step += 1
    ldrb  r1, [r2, #31]
    lsls  r0, r1, #1
    adds  r0, r0, r1
    lsls  r0, r0, #2
    adds  r0, r0, r3
    ldrb  r0, [r0, #8]
    cmp   r0, #0
    bne   .Lsec                @ next step exists -> run secondary effect
    movs  r0, #2               @ landing anim done -> request STANDING
    pop   {pc}

.Lsec:
    @ Secondary (effect) animation stepper, byte-for-byte the original logic.
    ldr   r1, .Lpool_fxctx
    ldr   r3, .Lpool_fxtable
    ldrb  r0, [r1, #2]         @ step2
    lsls  r0, r0, #3
    adds  r0, r0, r3           @ entry = table + step2*8
    ldrb  r1, [r1, #1]         @ frame2
    ldrh  r0, [r0, #4]         @ duration
    cmp   r1, r0
    bcc   .Lret255             @ still playing
    ldr   r1, .Lpool_fxctx
    movs  r0, #0
    strb  r0, [r1, #1]         @ frame2 = 0
    ldrb  r0, [r1, #2]
    adds  r0, #1
    strb  r0, [r1, #2]         @ step2 += 1
    ldrb  r0, [r1, #2]
    lsls  r0, r0, #3
    adds  r0, r0, r3
    ldrh  r0, [r0, #4]
    cmp   r0, #0
    bne   .Lret255
    strb  r0, [r1, #2]         @ step2 = 0 (r0 is 0 here; matches original 0x801190C)
.Lret255:
    movs  r0, #255             @ no pose request
    pop   {pc}

.Lcall_r3:
    bx    r3

.align 2
.Lpool_gwd:   .word gWarioData
.Lpool_probe: .word 0x0806DAC1
.Lpool_prim:  .word kPrimGp
.Lpool_prim2: .word kPrimSuperGp
.Lpool_fxctx: .word gLandingFxCtx
.Lpool_fxtable: .word kFxTable