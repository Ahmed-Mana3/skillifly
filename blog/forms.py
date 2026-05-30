from django import forms
from .models import Post


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = [
            'title', 'slug', 'language', 'content', 'status',
            'featured_image', 'featured_image_alt',
            'meta_description', 'canonical_url',
            'categories', 'tags',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'sf-input',
                'placeholder': 'Post title (English or Arabic)',
            }),
            'slug': forms.TextInput(attrs={
                'class': 'sf-input',
                'placeholder': 'Optional – auto-generated from title',
                'dir': 'ltr',
            }),
            'language': forms.Select(attrs={'class': 'sf-input', 'id': 'id_language'}),
            'status': forms.Select(attrs={'class': 'sf-input'}),
            'featured_image': forms.FileInput(attrs={'class': 'sf-input'}),
            'featured_image_alt': forms.TextInput(attrs={
                'class': 'sf-input',
                'placeholder': 'Describe the image for screen readers and search engines',
            }),
            'meta_description': forms.Textarea(attrs={
                'class': 'sf-input',
                'rows': 3,
                'maxlength': 160,
                'placeholder': 'Compelling 120–160 character summary shown in Google results',
            }),
            'canonical_url': forms.URLInput(attrs={
                'class': 'sf-input',
                'placeholder': 'https://... (leave blank to use the default URL)',
                'dir': 'ltr',
            }),
            'categories': forms.SelectMultiple(attrs={'class': 'sf-input'}),
            'tags': forms.SelectMultiple(attrs={'class': 'sf-input'}),
        }
