import os

views_path = r'd:\skillifly_dev\skillifly\payments\views.py'

with open(views_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# We want to remove lines 71 through 445 (inclusive, 1-based index)
# which means indices 70 through 444
keep_lines = lines[:70] + lines[445:]

with open(views_path, 'w', encoding='utf-8') as f:
    f.writelines(keep_lines)

print("Removed Kashier views successfully!")
