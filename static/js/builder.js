/** 
 * builder.js - Robust Portfolio Builder Engine
 * Handles dynamic formsets, section navigation, and UX enhancements.
 */

const Builder = {
    currentSection: 0,
    sectionNames: ['Personal', 'Skills', 'Education', 'Experience', 'Projects', 'Links'],

    init() {
        this.cacheDOM();
        this.bindEvents();
        this.checkInitialErrors();
        this.setupImagePreviews();
    },

    cacheDOM() {
        this.form = document.getElementById('portfolio-form');
        this.tabs = document.querySelectorAll('.tab-btn');
        this.panels = document.querySelectorAll('.section-panel');
        this.progressDots = document.querySelectorAll('.progress-dot');
        this.progressLabel = document.getElementById('progress-label');
    },

    bindEvents() {
        // Global removal listener
        document.addEventListener('click', (e) => {
            if (e.target.closest('.remove-item-btn')) {
                this.removeFormsetItem(e.target.closest('.remove-item-btn'));
            }
        });

        // Form monitoring
        this.form.addEventListener('change', () => {
            // Unsaved changes logic
        });

        // Smart Submit Handling
        this.form.addEventListener('submit', (e) => {
            // Find which button triggered the submission
            const submitter = e.submitter || document.activeElement;
            const isSubmitButton = submitter && (submitter.type === 'submit' || submitter.id?.includes('submit'));

            if (!this.form.checkValidity()) {
                e.preventDefault();
                this.jumpToFirstInvalid();
                this.showToast("Please fix the highlighted errors before launching.", "error");
            } else {
                // Pass the submitter button to the handler
                this.setSubmittingState(submitter);
                this.showToast("Saving changes & launching your portfolio...", "success");
            }
        });
    },

    jumpToFirstInvalid() {
        const firstInvalid = this.form.querySelector(':invalid');
        if (firstInvalid) {
            const panel = firstInvalid.closest('.section-panel');
            if (panel) {
                const index = Array.from(this.panels).indexOf(panel);
                this.switchSection(index);
                setTimeout(() => {
                    firstInvalid.focus();
                    firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Explicitly trigger the browser's native missing data message
                    firstInvalid.reportValidity();
                }, 100);
            } else {
                // Fallback if not inside a panel
                if (typeof firstInvalid.reportValidity === 'function') {
                    firstInvalid.reportValidity();
                }
            }
        }
    },

    showToast(message, type = "success") {
        let toast = document.getElementById('builder-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'builder-toast';
            toast.className = 'fixed bottom-8 left-1/2 -translate-x-1/2 z-[9999] px-6 py-3 rounded-2xl font-bold text-sm shadow-2xl transition-all duration-300 transform translate-y-20 opacity-0';
            document.body.appendChild(toast);
        }

        const colors = {
            success: "bg-emerald-500/90 text-white border border-emerald-400/50 backdrop-blur-xl",
            error: "bg-rose-500/90 text-white border border-rose-400/50 backdrop-blur-xl",
            info: "bg-blue-500/90 text-white border border-blue-400/50 backdrop-blur-xl"
        };

        toast.className = `fixed bottom-8 left-1/2 -translate-x-1/2 z-[9999] px-6 py-3 rounded-2xl font-bold text-sm shadow-2xl transition-all duration-300 transform ${colors[type]}`;
        toast.textContent = message;

        // Show
        setTimeout(() => {
            toast.classList.remove('translate-y-20', 'opacity-0');
        }, 10);

        // Hide after 4s (unless success, which usually means redirecting anyway)
        if (type !== 'success') {
            setTimeout(() => {
                toast.classList.add('translate-y-20', 'opacity-0');
            }, 4000);
        }
    },

    setSubmittingState(submitter) {
        // Use the button that triggered the submit, or fallback to the main one
        const btn = submitter && submitter.id ? submitter : document.getElementById('submit-btn');
        if (btn) {
            setTimeout(() => {
                btn.disabled = true;
                const spinner = `
                    <div class="flex items-center justify-center gap-3">
                        <svg class="animate-spin h-5 w-5 text-current" viewBox="0 0 24 24">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span>Launching...</span>
                    </div>
                `;
                btn.innerHTML = spinner;
            }, 0);
        }
    },

    switchSection(index) {
        if (index < 0 || index >= this.panels.length) return;

        // Animate out current
        this.panels[this.currentSection].classList.remove('active');
        if (this.tabs[this.currentSection]) {
            this.tabs[this.currentSection].classList.remove('active');
        }

        // Update indices
        this.currentSection = index;

        // Animate in new
        const nextPanel = this.panels[index];
        nextPanel.classList.add('active');
        if (this.tabs[index]) {
            this.tabs[index].classList.add('active');
        }

        // Update progress UI
        this.progressDots.forEach((dot, i) => {
            dot.classList.toggle('filled', i <= index);
        });
        
        // Dynamically get name from tab or use panel ID
        if (this.progressLabel) {
            if (this.tabs[index]) {
                this.progressLabel.textContent = this.tabs[index].textContent;
            } else {
                // Fallback for Solo mode: Get name from section header
                const header = nextPanel.querySelector('h2');
                if (header) this.progressLabel.textContent = header.textContent;
            }
        }

        // Scroll top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    /**
     * Django Formset Dynamic Addition
     * @param {string} prefix - The formset prefix (e.g., 'skills', 'projects')
     */
    addFormsetItem(prefix) {
        const totalFormsInput = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
        const count = parseInt(totalFormsInput.value);
        const container = document.getElementById(`${prefix}-container`);
        
        // Get the empty form template from the hidden script tag
        const templateSource = document.getElementById(`${prefix}-empty-form`);
        if (!templateSource) {
            console.warn(`No empty-form template found for prefix: ${prefix}`);
            return;
        }

        let html = templateSource.innerHTML;
        // Replace the __prefix__ placeholder with the actual index
        html = html.replace(/__prefix__/g, count);

        // Create a wrapper and inject
        const wrapper = document.createElement('div');
        wrapper.className = 'formset-item animate-slideIn';
        wrapper.innerHTML = html;

        // Add a remove button if not already in the template
        if (!wrapper.querySelector('.remove-item-btn')) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'remove-item-btn';
            btn.innerHTML = '✕';
            wrapper.appendChild(btn);
        }

        container.appendChild(wrapper);
        totalFormsInput.value = count + 1;

        // Initialize any specific logic for the new form (e.g., set up new image previews)
        this.setupImagePreviews();
    },

    removeFormsetItem(btn) {
        const item = btn.closest('.formset-item');
        const deleteCheckbox = item.querySelector('input[type="checkbox"][name$="-DELETE"]');
        
        if (deleteCheckbox) {
            // Existing item: Mark for deletion
            deleteCheckbox.checked = true;
            item.style.display = 'none';
            // Strip required attributes to prevent hidden validation errors
            item.querySelectorAll('[required]').forEach(el => el.removeAttribute('required'));
        } else {
            // Dynamic item (unsaved): Just remove from DOM
            item.remove();
            // Note: We don't necessarily need to decrement TOTAL_FORMS, 
            // but we could if it's the last one. Django handles high-index gaps.
        }
    },

    setupImagePreviews() {
        document.querySelectorAll('input[type="file"]').forEach(input => {
            if (input.dataset.previewInit) return;
            input.dataset.previewInit = "true";

            input.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;

                const reader = new FileReader();
                reader.onload = (event) => {
                    // Find or create preview box
                    const item = input.closest('.formset-item') || input.closest('.glass-panel');
                    let previewBox = item ? item.querySelector('.preview-box') : null;
                    
                    if (!previewBox) {
                        // Fallback: create one
                        previewBox = document.createElement('div');
                        previewBox.className = 'preview-box mt-4';
                        input.parentElement.appendChild(previewBox);
                    }
                    
                    previewBox.innerHTML = `<img src="${event.target.result}" alt="Preview" class="w-full h-full object-cover">`;
                };
                reader.readAsDataURL(file);
            });
        });
    },

    checkInitialErrors() {
        // If there are error messages, jump to that section
        const firstError = document.querySelector('.error-msg');
        if (firstError) {
            const panel = firstError.closest('.section-panel');
            const panelId = panel ? panel.id.replace('section-', '') : null;
            
            if (panelId !== null) {
                this.switchSection(parseInt(panelId));
                setTimeout(() => {
                    firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 300);
            }

            // Mark tabs with errors
            document.querySelectorAll('.section-panel').forEach((p, i) => {
                if (p.querySelector('.error-msg')) {
                    this.tabs[i].classList.add('has-error');
                }
            });
        }
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => Builder.init());
