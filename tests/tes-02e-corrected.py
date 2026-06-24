# tests/test_02f_ips_supplier.py — Button Blasters
# TEST 2f: DEFINITIVE IPS init using exact supplier sequence
#
# Key changes based on supplier files:
#  1. Pixel format 0x55 = RGB565 (not 0x66 = RGB666 we used before)
#  2. Command 0x21 (display inversion ON) — required for IPS
#  3. Command 0xE9 = 0x00 — IPS specific
#  4. VCOM = 0x4D (was 0x12 before — critical difference!)
#  5. C0 power = 0x0F,0x0F (was 0x17,0x15)
#  6. C1 = 0x47 (was 0x41)
#  7. Sleep out BEFORE all other commands, with 480ms delay
#  8. Backlight on VBUS (5V) via GP13 — schematic shows MOSFET
#     switched from BL pin, powered from +5V rail
#
# WIRING CHANGE: Move LED pin wire to VBUS (5V pin on Pico)
# with GP13 as the gate signal. OR just try VBUS directly first.
#
# Pins: SCK=GP2 MOSI=GP3 MISO=GP4 CS=GP6 DC=GP12 RST=GP17 LED=GP13

import time
from machine import SPI, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 2f: Supplier IPS init")
print("="*48)

# ── Backlight — try driving BL pin HIGH via GPIO ──────────────────
BL = Pin(13, Pin.OUT, value=1)
print("\n[0] BL pin (GP13) driven HIGH")
print("    Also try: wire LED pin to VBUS (5V) directly if no response")
time.sleep_ms(500)

# ── SPI ───────────────────────────────────────────────────────────
spi = SPI(0, baudrate=20_000_000, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
cs  = Pin(6,  Pin.OUT, value=1)
dc  = Pin(12, Pin.OUT, value=1)
rst = Pin(17, Pin.OUT, value=1)
print("[1] SPI 20MHz, CS=6 DC=12 RST=17")

# ── Reset ─────────────────────────────────────────────────────────
rst.value(1); time.sleep_ms(50)
rst.value(0); time.sleep_ms(50)
rst.value(1); time.sleep_ms(200)
print("[2] Reset complete")

def cmd(c, *data):
    cs.value(0)
    dc.value(0); spi.write(bytes([c]))
    if data:
        dc.value(1); spi.write(bytes(data))
    cs.value(1)

# ── Supplier IPS init sequence (from BOE3.5IPS file) ─────────────
print("[3] Sending supplier IPS init sequence...")

# Sleep out FIRST with long delay (supplier specifies Delay(480))
cmd(0x11)              # sleep out
time.sleep_ms(480)     # supplier specifies 480ms — was 150ms before

# Adjust control
cmd(0xF7, 0xA9, 0x51, 0x2C, 0x82)

# Power control — NOTE different values from TN init!
cmd(0xC0, 0x0F, 0x0F)  # was 0x17,0x15 — KEY DIFFERENCE
cmd(0xC1, 0x47)         # was 0x41 — KEY DIFFERENCE

# VCOM — NOTE 0x4D not 0x12 — CRITICAL DIFFERENCE
cmd(0xC5, 0x00, 0x4D, 0x80)   # was 0x00,0x12,0x80

# Frame rate
cmd(0xB1, 0xB0, 0x11)

# Display inversion control
cmd(0xB4, 0x02)

# MADCTL — landscape, BGR
cmd(0x36, 0x48)

# Pixel format — RGB565 (0x55 not 0x66!)
cmd(0x3A, 0x55)        # KEY DIFFERENCE — was 0x66 (18-bit), now 0x55 (16-bit)

# IPS SPECIFIC — display inversion ON
cmd(0x21)              # MISSING FROM ALL OUR PREVIOUS INITS

# IPS SPECIFIC
cmd(0xE9, 0x00)

# Adjust control again
cmd(0xF7, 0xA9, 0x51, 0x2C, 0x82)

# Positive gamma
cmd(0xE0, 0x00,0x07,0x0B,0x03,0x0F,0x05,0x30,0x56,
          0x47,0x04,0x0B,0x0A,0x2D,0x37,0x0F)

# Negative gamma
cmd(0xE1, 0x00,0x0E,0x13,0x04,0x11,0x07,0x39,0x45,
          0x50,0x07,0x10,0x0D,0x32,0x36,0x0F)

# Display on
cmd(0x29)
time.sleep_ms(50)
print("    ✓ IPS init complete")

# ── Fill colours ──────────────────────────────────────────────────
def set_win(x0,y0,x1,y1):
    cs.value(0)
    dc.value(0);spi.write(b'\x2A');dc.value(1)
    spi.write(bytes([x0>>8,x0&0xFF,x1>>8,x1&0xFF]))
    dc.value(0);spi.write(b'\x2B');dc.value(1)
    spi.write(bytes([y0>>8,y0&0xFF,y1>>8,y1&0xFF]))
    dc.value(0);spi.write(b'\x2C');dc.value(1)

def fill(r,g,b,W=480,H=320):
    # RGB565 pixel (0x55 pixel format — 16-bit, 2 bytes per pixel)
    c = ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    hi=c>>8; lo=c&0xFF
    chunk=bytes([hi,lo]*64); total=W*H
    set_win(0,0,W-1,H-1)
    for _ in range(total//64): spi.write(chunk)
    if total%64: spi.write(bytes([hi,lo]*(total%64)))
    cs.value(1)

print("\n[4] Colour fills — watch display:")
for name,r,g,b in [("RED",255,0,0),("GREEN",0,255,0),
                   ("BLUE",0,0,255),("WHITE",255,255,255)]:
    t=time.ticks_ms()
    fill(r,g,b)
    ms=time.ticks_diff(time.ticks_ms(),t)
    print(f"    {name}: {ms}ms")
    time.sleep_ms(800)

print("\n[5] Test pattern...")
fill(20,10,60)     # dark purple bg
# colour bars across top third
bars=[(255,0,0),(255,165,0),(255,255,0),
      (0,255,0),(0,0,255),(75,0,130),(148,0,211)]
bw=480//len(bars)
for i,(r,g,b) in enumerate(bars):
    c=((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    hi=c>>8;lo=c&0xFF
    chunk=bytes([hi,lo]*64);total=bw*(320//3)
    set_win(i*bw,0,(i+1)*bw-1,320//3-1)
    cs.value(0);dc.value(1)
    for _ in range(total//64): spi.write(chunk)
    cs.value(1)
print("    ✓ Test pattern drawn")

print()
print("="*48)
print("  TEST 2f COMPLETE — Supplier IPS init")
print()
print("  Key differences from all previous tests:")
print("  - Pixel format 0x55 (RGB565) not 0x66 (RGB666)")
print("  - VCOM 0x4D not 0x12")  
print("  - cmd(0x21) display inversion ON for IPS")
print("  - Sleep out FIRST with 480ms delay")
print("  - Power regs C0/C1 IPS values")
print()
print("  If colours show: display is working!")
print("  If backlight still dark: wire LED to VBUS (5V)")
print("  pin on Pico directly and rerun")
print("="*48+"\n")