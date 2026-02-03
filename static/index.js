// index.js - Simplified version with Django handling selection

document.addEventListener('DOMContentLoaded', function () {
    // Template cards functionality
    const cards = Array.from(document.querySelectorAll('.template-card'));
    const continueBtn = document.querySelector('.builder-btn');
    const previewBtn = document.querySelector('.preview-btn');

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
            if (themeInput) {
                themeInput.value = card.dataset.theme;
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
