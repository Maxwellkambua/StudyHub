# run_seed.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import your seed logic
from seed import *

# The seed.py script runs on import, so nothing else is needed here.
print("Seeding process completed.")
