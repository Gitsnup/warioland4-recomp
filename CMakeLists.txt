cmake_minimum_required(VERSION 3.20)
project(WarioLand4Recomp C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include(CTest)

# Path to the platform core (sibling checkout in this repo). Override
# with -DGBARECOMP_ROOT=... for a different layout.
set(GBARECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/gbarecomp"
    CACHE PATH "Path to gbarecomp platform core")

if(NOT EXISTS "${GBARECOMP_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR
        "GBARECOMP_ROOT does not point to a gbarecomp checkout: ${GBARECOMP_ROOT}")
endif()

# Expose recomp-ui's shared in-game model to the platform runtime.
set(GBARECOMP_RUNTIME_UI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/recomp-ui"
    CACHE PATH "recomp-ui root used by the live GBA runtime adapter")
set(RECOMP_UI_ROOT "${GBARECOMP_RUNTIME_UI_ROOT}"
    CACHE PATH "Path to the shared recomp-ui checkout")

# Pull in the platform core targets. This makes gbarecomp_runtime,
# gbarecomp_debug, gbarecomp_gba, gbarecomp_armv4t available as links.
add_subdirectory("${GBARECOMP_ROOT}" gbarecomp_build EXCLUDE_FROM_ALL)

# ─────────────────────────────────────────────────────────────────────
# WarioLand4Recomp — the game binary. Links the statically recompiled
# guest code (variants/warioland4/generated/*.cpp) against the runtime
# libs. Build it with tools/regen.sh (see README).
# ─────────────────────────────────────────────────────────────────────
file(GLOB WL4_GENERATED_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/variants/warioland4/generated/*.cpp")

set(WL4_RUNTIME_SOURCES
    src/main.cpp
    ${WL4_GENERATED_SOURCES}
)

# The recompiler normally emits kDispatchTable/kDispatchTableLen in
# generated/. Until regen produces them, link the engine's empty stubs so
# the scaffold binary still builds and boots headless.
if(NOT WL4_GENERATED_SOURCES)
    list(APPEND WL4_RUNTIME_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/scaffold_dispatch_stub.cpp")
endif()

# On Android the shared library must be named `main` (libmain.so is what
# SDLActivity loads); desktop keeps the executable.
if(ANDROID)
    set(WL4_TARGET main)
    add_library(${WL4_TARGET} SHARED ${WL4_RUNTIME_SOURCES})
else()
    set(WL4_TARGET WarioLand4Recomp)
    add_executable(${WL4_TARGET} ${WL4_RUNTIME_SOURCES})
endif()

target_include_directories(${WL4_TARGET} PRIVATE
    "${GBARECOMP_ROOT}/src/armv4t"
    "${GBARECOMP_ROOT}/src/gba"
    "${GBARECOMP_ROOT}/src/runtime"
    "${GBARECOMP_ROOT}/src/debug"
    src
)

target_link_libraries(${WL4_TARGET} PRIVATE
    # --start-group/--end-group lets ld re-iterate the gbarecomp static
    # libs to resolve their mutual references.
    "-Wl,--start-group"
    gbarecomp_runtime
    gbarecomp_debug
    gbarecomp_gba
    gbarecomp_armv4t
    "-Wl,--end-group"
)

target_compile_definitions(${WL4_TARGET} PRIVATE
    GBARECOMP_DEFAULT_DEBUG_PORT=19842
    GBARECOMP_WINDOW_TITLE="WarioLand4Recomp"
    GBARECOMP_DEFAULT_GAME_CONFIG="variants/warioland4/game.toml"
)

# The generated shards are enormous single TUs (hundreds of recompiled
# functions each). Host compiles of the game binary stay -O2, but the
# guest shards build -O1 -g0: runtime speed difference is negligible
# next to the interpreter, and peak gcc memory drops several-fold —
# which matters on 4 GB machines (and this project's build host).
foreach(shard ${WL4_GENERATED_SOURCES})
    set_property(SOURCE ${shard} PROPERTY COMPILE_OPTIONS "-O1;-g0")
endforeach()

# ─────────────────────────────────────────────────────────────────────
# recomp-ui pre-boot launcher (Dear ImGui). Isolated in its own static
# lib so recomp-ui's sources + RECOMP_LAUNCHER define never touch the
# giant generated/*.cpp TU flags — only main.cpp (gated on
# GBAGAME_RECOMP_UI) and launcher_boot.cpp know the launcher exists.
# ─────────────────────────────────────────────────────────────────────
option(GBAGAME_RECOMP_UI "Build the recomp-ui pre-boot launcher" ON)
if(GBAGAME_RECOMP_UI)
    include(${RECOMP_UI_ROOT}/recomp_ui.cmake)
    add_library(game_launcher_ui STATIC src/game_launcher_boot.cpp)
    target_include_directories(game_launcher_ui PRIVATE
        "${GBARECOMP_ROOT}/src/runtime"   # launcher_seam.h + runtime.h
        "${GBARECOMP_ROOT}/src/gba"
        src
    )
    # WL4 does not ship the .gbamod catalog, so the launcher must not be
    # built with GBARECOMP_ENABLE_MODS (the engine's mod_runtime symbols
    # would have no definition to link against).
    # sources, includes, RECOMP_LAUNCHER, asset staging
    recomp_target_launcher_ui(game_launcher_ui
        CONSOLE gba)
    if(NOT ANDROID)
        find_package(SDL2 REQUIRED)
    endif()
    target_link_libraries(game_launcher_ui PUBLIC SDL2::SDL2)
    if(WIN32)
        target_link_libraries(game_launcher_ui PUBLIC opengl32)
    endif()
    target_link_libraries(${WL4_TARGET} PRIVATE game_launcher_ui)
    set_property(SOURCE src/main.cpp APPEND PROPERTY COMPILE_DEFINITIONS GBAGAME_RECOMP_UI)
endif()

if(MSVC)
    target_link_options(${WL4_TARGET} PRIVATE /STACK:268435456)
elseif(MINGW OR WIN32 OR CMAKE_SYSTEM_NAME STREQUAL "MSYS")
    target_link_options(${WL4_TARGET} PRIVATE -Wl,--stack,268435456)
endif()
