"""Make the ``tasktracker`` package importable when pytest runs the sample's tests.

pytest discovers this conftest (it sits above ``tests/``) and adds this directory to
``sys.path``, so ``import tasktracker`` resolves without installing the sample.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
