import os

views_path = r'd:\skillifly_dev\skillifly\payments\views.py'

with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

functions = """
@login_required
def payment_success(request):
    return render(request, 'payment/payment_success.html')

@login_required
def payment_failure(request):
    error_message = request.session.pop('payment_error', "We couldn't process your payment. Please ensure your details are correct and try again.")
    return render(request, 'payment/payment_failure.html', {'error_message': error_message})
"""

with open(views_path, 'w', encoding='utf-8') as f:
    f.write(content + functions)

print("Restored successfully!")
