cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Board")
include(pico_sdk_import.cmake)

project(dcbridge C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(dcbridge
    src/main.c
    src/usb_descriptors.c
    src/dcbus.c
    src/baud.c
    src/w5500_emu.c
    src/sd_emu.c
    src/sd_link.c
    src/settings.c
)

pico_generate_pio_header(dcbridge ${CMAKE_CURRENT_LIST_DIR}/src/dcbus.pio)

target_include_directories(dcbridge PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
    ${PICO_TINYUSB_PATH}/lib/networking)   # rndis_protocol.h, needed by the ECM driver
target_compile_options(dcbridge PRIVATE -Wall -Wextra -Wno-unused-parameter -O2)

target_link_libraries(dcbridge PRIVATE
    pico_stdlib
    pico_multicore
    pico_unique_id
    hardware_pio
    hardware_flash
    hardware_vreg
    hardware_watchdog
    tinyusb_device
    tinyusb_board
)

# Run everything from SRAM: core1 must never stall on an XIP cache miss.
pico_set_binary_type(dcbridge copy_to_ram)

# No stdio over USB/UART: USB is ours, UART0 pins are the Dreamcast's.
pico_enable_stdio_usb(dcbridge 0)
pico_enable_stdio_uart(dcbridge 0)

pico_add_extra_outputs(dcbridge)
