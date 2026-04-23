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
        this.panels = document.querySelectorAll('.section-panel');
        this.tabs = document.querySelectorAll('.tab-btn');
        this.category = document.getElementById('builder-container')?.dataset.category || 'developer';
    
        this.initReordering();
        this.progressLabel = document.getElementById('progress-label');
    },

    initReordering() {
        const container = document.getElementById('builder-panels');
        if (!container) return;

        // Define preferred order per category
        // Indices relative to default: 0:Identity, 1:Expertise, 2:Education, 3:Experience, 4:Projects, 5:Links
        const orders = {
          'student': [0, 2, 1, 3, 4, 5],      // Education first
          'video_editor': [0, 4, 1, 3, 2, 5], // Projects first
          'developer': [0, 1, 3, 4, 2, 5]     // Expertise/Experience first
        };

        const preferredOrder = orders[this.category] || orders['developer'];
        const panelArray = Array.from(this.panels);
        
        // Clear and re-append in preferred order
        container.innerHTML = '';
        preferredOrder.forEach(idx => {
          if (panelArray[idx]) container.appendChild(panelArray[idx]);
        });

        // Re-append tabs in order
        const tabContainer = document.querySelector('.builder-tabs');
        if (tabContainer) {
            const tabArray = Array.from(this.tabs);
            tabContainer.innerHTML = '';
            preferredOrder.forEach((idx, stepNum) => {
                const tab = tabArray[idx];
                if (tab) {
                    // Update tab number label visually
                    const numSpan = tab.querySelector('.tab-num');
                    if (numSpan) numSpan.textContent = stepNum + 1;
                    
                    // Update the onclick attribute to match the NEW index (stepNum)
                    tab.setAttribute('onclick', `Builder.switchSection(${stepNum})`);
                    
                    tabContainer.appendChild(tab);
                }
            });
        }

        // Re-query panels and tabs to update the references in correct order
        this.panels = document.querySelectorAll('.section-panel');
        this.tabs = document.querySelectorAll('.tab-btn');
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
                this.switchSection(index, true); // Pass true to bypass validation when jumping to error
                setTimeout(() => {
                    firstInvalid.focus();
                    firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Explicitly trigger the browser's native missing data message
                    firstInvalid.reportValidity();
                    
                    // Add a temporary highlight class
                    firstInvalid.classList.add('error-pulse');
                    setTimeout(() => firstInvalid.classList.remove('error-pulse'), 2000);
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

    validateSection(index) {
        const panel = this.panels[index];
        if (!panel) return true;

        const inputs = panel.querySelectorAll('input, textarea, select');
        let isValid = true;
        let firstInvalid = null;

        inputs.forEach(input => {
            // Skip hidden inputs or those inside hidden containers (like marked for delete)
            if (input.type === 'hidden' || input.closest('[style*="display: none"]')) return;

            if (!input.checkValidity()) {
                isValid = false;
                if (!firstInvalid) firstInvalid = input;
                
                // Add error styling
                input.classList.add('invalid-field');
            } else {
                input.classList.remove('invalid-field');
            }
        });

        if (!isValid && firstInvalid) {
            firstInvalid.reportValidity();
            firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            this.showToast("Please complete the required fields in this section.", "error");
        }

        return isValid;
    },

    switchSection(index, bypassValidation = false) {
        if (index < 0 || index >= this.panels.length) return;

        // Only validate if moving FORWARD and not bypassing
        if (!bypassValidation && index > this.currentSection) {
            // Validate all sections from current up to (index - 1)
            // Usually it's just the current one, but in case they click a dot ahead
            for (let i = this.currentSection; i < index; i++) {
                if (!this.validateSection(i)) return;
            }
        }

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
        this.tabs.forEach((tab, i) => {
            tab.classList.toggle('active', i === index);
            tab.classList.toggle('filled', i < index);
        });
        
        // Dynamically get name from tab or use panel ID
        if (this.progressLabel) {
            if (this.tabs[index]) {
                const span = this.tabs[index].querySelector('span:not(.tab-num)');
                this.progressLabel.textContent = span ? span.textContent : this.tabs[index].textContent;
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
