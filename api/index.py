import os
import sys

# إضافة المجلد الرئيسي (Root) إلى مسار بايثون حتى يتمكن من العثور على main.py
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from main import app
