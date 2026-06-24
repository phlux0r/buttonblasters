import time
from machine import Pin, SPI
from ili9488 import ILI9488

print("Performing physical hardware reset...")
# Explicitly force Reset low then high to clear the controller's crashed state
rst_pin = Pin(12, Pin.OUT, value=0)
time.sleep_ms(100)
rst_pin.value(1)
time.sleep_ms(100)

print("Initializing SPI0 on alternative hardware pins...")
spi0 = SPI(0, baudrate=10000000, polarity=0, phase=0, 
           sck=Pin(18), mosi=Pin(19), miso=Pin(4))

print("Spawning driver with hardware overrides...")
display = ILI9488(spi=spi0, cs=6, dc=12, rst=17)

print("Starting Color Cycle Sync loop...")
while True:
    print("Red Canvas")
    display.fill_screen(0xFF, 0x00, 0x00)
    time.sleep(1)
    
    print("Green Canvas")
    display.fill_screen(0x00, 0xFF, 0x00)
    time.sleep(1)
    
    print("Blue Canvas")
    display.fill_screen(0x00, 0x00, 0xFF)
    time.sleep(1)