"""
Pytest configuration for the Email Job Extraction Agent test suite.

Adds the src/ directory to sys.path so that test modules can import
source modules directly (e.g. `import extractor`) without installing
the package.
"""

import sys
from pathlib import Path

# Add src/ to the path — all source modules live there
sys.path.insert(0, str(Path(__file__).parent.parent))
