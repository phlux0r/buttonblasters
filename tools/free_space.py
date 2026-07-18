import os

# Get filesystem statistics
stat = os.statvfs('/')

block_size = stat[0]
free_blocks = stat[3]

# Calculate free space in bytes and megabytes
free_bytes = block_size * free_blocks
free_mb = free_bytes / 1024 / 1024

print(f"Free space: {free_bytes} bytes")
print(f"Free space: {free_mb:.2f} MB")
