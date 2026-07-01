#!/usr/bin/env python3
"""Allow running as: python -m astromind_praxis"""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
    from .main import stdio_loop
    stdio_loop()
else:
    from .main import main
    main()
