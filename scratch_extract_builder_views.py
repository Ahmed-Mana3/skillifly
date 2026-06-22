import sys

def extract_lines(filepath, line_ranges):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    extracted = []
    for start, end in line_ranges:
        # line numbers are 1-based, indices are 0-based
        extracted.extend(lines[start-1:end])
        extracted.append("\n\n")
    return "".join(extracted)

core_views = "d:\\skillifly_dev\\skillifly\\core\\views.py"
builder_views = "d:\\skillifly_dev\\skillifly\\builder\\views.py"

header = """from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from datetime import date

# Import models from core
from core.models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment, Review, Showcase, SEOSettings, ManualPayment, Creator, ProjectCategory

# Import forms from builder
from builder.forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
    CreatorFormSet,
    ProjectCategoryFormSet,
    SkillFormSetUpdate,
    EducationFormSetUpdate,
    ExperienceFormSetUpdate,
    ProjectFormSetUpdate,
    LinkFormSetUpdate,
    CreatorFormSetUpdate,
    ProjectCategoryFormSetUpdate,
)

"""

line_ranges = [
    (21, 68),     # ajax_save_category
    (71, 82),     # ajax_delete_category
    (683, 766),   # builder_view
    (769, 924),   # update_portfolio_view
    (927, 1081),  # save_portfolio_data
]

extracted_content = extract_lines(core_views, line_ranges)

with open(builder_views, 'w', encoding='utf-8') as f:
    f.write(header + extracted_content)

print("Extraction complete!")
