def remove_lines(filepath, ranges_to_remove):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Sort ranges in reverse order so deleting doesn't mess up indices
    sorted_ranges = sorted(ranges_to_remove, key=lambda x: x[0], reverse=True)
    
    for start, end in sorted_ranges:
        del lines[start-1:end]
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)

core_views = "d:\\skillifly_dev\\skillifly\\core\\views.py"

line_ranges = [
    (21, 68),     # ajax_save_category
    (71, 82),     # ajax_delete_category
    (683, 766),   # builder_view
    (769, 924),   # update_portfolio_view
    (927, 1081),  # save_portfolio_data
]

remove_lines(core_views, line_ranges)
print("Lines removed from core/views.py")
