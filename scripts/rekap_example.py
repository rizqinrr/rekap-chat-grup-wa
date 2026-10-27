#!/usr/bin/env python3
"""Digest cron untuk grup: NGOMONGIN AI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rekap_lib import main

main("<group-id>@g.us")
