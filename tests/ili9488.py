import time
from machine import Pin

class ILI9488:
    def __init__(self, spi, cs, dc, rst, width=320, height=480):
        self.spi = spi
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.width = width
        self.height = height
        self.init_display()

    def write_cmd(self, cmd):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([cmd]))
        self.cs.value(1)

    def write_data(self, data):
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(bytes([data]))
        self.cs.value(1)

    def init_display(self):
        # Hardware Reset Pulse
        self.rst.value(1)
        time.sleep_ms(10)
        self.rst.value(0)
        time.sleep_ms(20)
        self.rst.value(1)
        time.sleep_ms(120)

        # Standard Wake & Interface Settings
        self.write_cmd(0x11) # Sleep Out
        time.sleep_ms(120)
        
        self.write_cmd(0x3A) # Interface Pixel Format
        self.write_data(0x66) # 18-bit color mode (Required by ILI9488 SPI SPI)

        # =======================================================
        # YOUR CUSTOM HARDWARE FIXES BAKED IN DIRECTLY
        # =======================================================
        print("Injecting custom VCOM adjustment...")
        self.write_cmd(0xC5) # VCOM Control
        self.write_data(0x00)
        self.write_data(0x4D) # Your magic VCOM threshold byte!
        self.write_data(0x80)

        print("Enabling display color inversion...")
        self.write_cmd(0x21) # Display Inversion ON
        
        self.write_cmd(0x36) # Memory Access Control (Rotation layout)
        self.write_data(0x48) # Default Portrait alignment
        # =======================================================

        self.write_cmd(0x29) # Display ON
        time.sleep_ms(20)

    def fill_screen(self, r, g, b):
        """Fills screen using 18-bit color formatting native to ILI9488 SPI"""
        self.write_cmd(0x2A) # Column Address Set
        self.write_data(0x00)
        self.write_data(0x00)
        self.write_data((self.width - 1) >> 8)
        self.write_data((self.width - 1) & 0xFF)

        self.write_cmd(0x2B) # Page Address Set
        self.write_data(0x00)
        self.write_data(0x00)
        self.write_data((self.height - 1) >> 8)
        self.write_data((self.height - 1) & 0xFF)

        self.write_cmd(0x2C) # Memory Write
        
        # Optimize rendering speed by transmitting rows in blocks
        pixel_bytes = bytes([r, g, b]) * self.width
        self.dc.value(1)
        self.cs.value(0)
        for _ in range(self.height):
            self.spi.write(pixel_bytes)
        self.cs.value(1)