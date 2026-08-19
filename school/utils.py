from core.models import School, SchoolStudent


def enroll_in_school(user, coupon_code):
    """
    If `coupon_code` matches a School's discount code, add the user to that
    school as a student (idempotent per user+school). Returns the
    SchoolStudent created/found, or None when no school matches.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not coupon_code:
        return None

    code = coupon_code.strip().upper()
    try:
        school = School.objects.get(discount_code=code)
    except School.DoesNotExist:
        return None

    student, created = SchoolStudent.objects.get_or_create(
        school=school,
        user=user,
        defaults={
            "is_hidden": False,
            "order": 0,
        },
    )
    return student
