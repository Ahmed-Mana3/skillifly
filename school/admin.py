from django.contrib import admin

from core.models import School, SchoolStudent, SchoolVideoRating, SchoolStudentRating, SchoolVideoComment


class SchoolStudentInline(admin.TabularInline):
    model = SchoolStudent
    extra = 0
    fields = ('user', 'order', 'is_hidden')


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'discount_code', 'number_of_students', 'has_logo')
    search_fields = ('name', 'slug', 'discount_code')
    list_filter = ('discount_code',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SchoolStudentInline]

    def has_logo(self, obj):
        return bool(obj.logo)
    has_logo.short_description = 'Logo'


@admin.register(SchoolStudent)
class SchoolStudentAdmin(admin.ModelAdmin):
    list_display = ('user', 'school', 'order', 'is_hidden')
    list_filter = ('school', 'is_hidden')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')


@admin.register(SchoolVideoRating)
class SchoolVideoRatingAdmin(admin.ModelAdmin):
    list_display = ('project', 'value', 'created_at')
    list_filter = ('value',)
    raw_id_fields = ('project',)


@admin.register(SchoolStudentRating)
class SchoolStudentRatingAdmin(admin.ModelAdmin):
    list_display = ('student', 'value', 'created_at')
    list_filter = ('value',)


@admin.register(SchoolVideoComment)
class SchoolVideoCommentAdmin(admin.ModelAdmin):
    list_display = ('project', 'author_name', 'stars', 'created_at')
    list_filter = ('stars',)
    raw_id_fields = ('project',)
