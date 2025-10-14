'''
This module contains constants, representing
constraints to prevent possible crushes due to
limitations of RPI.
'''
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB limit for HTML responses
MIN_DISK_SPACE_MB = 10  # Minimum free disk space required
STATE_FILE_MAX_SIZE = 1 * 1024 * 1024  # 1MB max for state files
