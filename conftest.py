import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

# Mockear boto3 antes de importar lambda_function
sys.modules['boto3'] = MagicMock()