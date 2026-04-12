// index.js - Simplified version with Django handling selection

document.addEventListener('DOMContentLoaded', function () {
    // Category tabs functionality
    const categoryTabs = document.querySelectorAll('.category-tab');
    const cards = Array.from(document.querySelectorAll('.template-card'));
    const continueBtn = document.querySelector('.builder-btn');
    const previewBtn = document.querySelector('.preview-btn');

    // Category filtering
    categoryTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Update active tab
            categoryTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Filter templates by category
            const selectedCategory = tab.dataset.category;
            cards.forEach(card => {
                if (card.dataset.category === selectedCategory) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });

            // Clear selection when switching categories
            cards.forEach(c => c.classList.remove('selected'));
            updateContinueState();
        });
    });

    // Initialize - show only first category's templates
    if (categoryTabs.length > 0) {
        const firstCategory = categoryTabs[0].dataset.category;
        cards.forEach(card => {
            if (card.dataset.category !== firstCategory) {
                card.style.display = 'none';
            }
        });
    }

    function updateContinueState() {
        const selected = cards.find(c => c.classList.contains('selected'));
        if (selected) {
            if (continueBtn) {
                continueBtn.classList.remove('disabled');
                // Django will handle the theme in the session/database
            }
            if (previewBtn) {
                previewBtn.classList.remove('disabled');
                previewBtn.href = selected.dataset.theme || '/theme-1/';
            }
        } else {
            if (continueBtn) {
                continueBtn.classList.add('disabled');
                continueBtn.href = '#';
            }
            if (previewBtn) {
                previewBtn.classList.add('disabled');
                previewBtn.href = '#';
            }
        }
    }

    cards.forEach(card => {
        card.tabIndex = 0;
        card.addEventListener('click', () => {
            cards.forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            updateContinueState();

            // Store selection in a hidden form field instead of localStorage
            const themeInput = document.getElementById('selectedTheme');
            const categoryInput = document.getElementById('selectedCategory');
            if (themeInput) {
                themeInput.value = card.dataset.theme;
            }
            if (categoryInput) {
                categoryInput.value = card.dataset.category;
            }
        });
        card.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });

    if (continueBtn) {
        continueBtn.addEventListener('click', (e) => {
            if (continueBtn.classList.contains('disabled')) {
                e.preventDefault();
                const first = cards[0];
                first && first.focus();
            }
        });
    }

    if (previewBtn) {
        previewBtn.addEventListener('click', (e) => {
            if (previewBtn.classList.contains('disabled')) {
                e.preventDefault();
                const first = cards[0];
                first && first.focus();
                return;
            }
        });
    }

    updateContinueState();
});
