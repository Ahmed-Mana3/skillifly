import os

core_views_path = r'd:\skillifly_dev\skillifly\core\views.py'
payments_views_path = r'd:\skillifly_dev\skillifly\payments\views.py'

with open(core_views_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

def extract(start_line, end_line):
    # 1-indexed, inclusive
    return lines[start_line-1 : end_line]

# Extract the chunks
chunk1 = extract(1168, 1195)
chunk2 = extract(1231, 1538)
chunk3 = extract(1540, 1623)
chunk4 = extract(1928, 2192)
chunk5 = extract(2433, 2477)

all_extracted_lines = chunk1 + chunk2 + chunk3 + chunk4 + chunk5
extracted_text = "".join(all_extracted_lines)

# Fix relative imports
extracted_text = extracted_text.replace('from .models', 'from core.models')
extracted_text = extracted_text.replace('from .forms', 'from core.forms')
extracted_text = extracted_text.replace('from .tasks', 'from core.tasks')

# Create payments/views.py
payments_code = """import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import timedelta
import base64
from google import genai
from google.genai import types

import requests as _requests
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse

from core.models import UserPayment, Subscription, Profile, CustomUser, DiscountCode, SiteSettings, ManualPayment
from core.views import process_affiliate_earning

logger = logging.getLogger('payments')

""" + extracted_text

with open(payments_views_path, 'w', encoding='utf-8') as f:
    f.write(payments_code)

keep_lines = []
for i, line in enumerate(lines):
    idx = i + 1
    if 1168 <= idx <= 1195: continue
    if 1231 <= idx <= 1538: continue
    if 1540 <= idx <= 1623: continue
    if 1928 <= idx <= 2192: continue
    if 2433 <= idx <= 2477: continue
    keep_lines.append(line)

with open(core_views_path, 'w', encoding='utf-8') as f:
    f.write("".join(keep_lines))

print("Extraction completed successfully!")
