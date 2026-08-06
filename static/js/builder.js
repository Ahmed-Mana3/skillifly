/** 
 * builder.js - Robust Portfolio Builder Engine
 * Handles dynamic formsets, section navigation, and UX enhancements.
 */

const Builder = {
    currentSection: 0,
    sectionNames: ['Personal', 'Skills', 'Education', 'Experience', 'Projects', 'Links', 'Creators', 'Reviews'],

    I18N: Object.assign({
        stepOf: 'Step {step} of {total}',
        beforeLaunchErrors: 'Please fix the highlighted errors before launching.',
        savingLaunch: 'Saving changes & launching your portfolio...',
        sectionRequired: 'Please complete the required fields in this section.',
        launching: 'Launching...',
        noFileChosen: 'No file chosen',
        createCategory: 'Create a Category',
        editCategory: 'Edit Category',
        existingThumbnail: 'Existing thumbnail',
        confirmDeleteCollection: 'Are you sure you want to delete this collection? All projects inside it will automatically become Uncategorized.',
        securityToken: 'Security token not found. Please reload.',
        deletingCollection: 'Deleting collection...',
        failedDeleteCategory: 'Failed to delete category.',
        noCollections: 'No collections created yet. Projects will display in "Other Videos".',
        collectionDeleted: 'Collection deleted successfully.',
        errorConnecting: 'Error connecting to server.',
        configError: 'Configuration error — please refresh and try again.',
        saving: 'Saving...',
        failedSaveCategory: 'Failed to save category.',
        editCollection: 'Edit Collection',
        deleteCollection: 'Delete Collection',
        collectionCreated: 'Collection "{name}" created!',
        collectionUpdated: 'Collection "{name}" updated!',
        networkError: 'Network error — please try again.',
        imgAlt: 'Preview',
        reviewListed: 'Review listed on portfolio!',
        reviewHidden: 'Review hidden from portfolio.'
    }, window.BuilderI18n || {}),

    t(key, vars) {
        let s = this.I18N[key] !== undefined ? this.I18N[key] : key;
        if (vars) {
            for (const k in vars) {
                s = s.split('{' + k + '}').join(String(vars[k]));
            }
        }
        return s;
    },

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

        // 0:Identity, 1:Expertise, 2:Education, 3:Experience, 4:Projects, 5:Links, 6:Creators, 7:Reviews
        const orders = {
          'student': [0, 2, 1, 3, 4, 6, 7, 5],
          'video_editor': [0, 4, 1, 6, 7, 3, 2, 5],
          'developer': [0, 1, 3, 4, 6, 7, 2, 5]
        };

        const preferredOrder = orders[this.category] || orders['developer'];
        const panelArray = Array.from(this.panels);
        
        const validOrder = preferredOrder.filter(idx => panelArray[idx]);

        container.innerHTML = '';
        validOrder.forEach((idx, stepNum) => {
            container.appendChild(panelArray[idx]);
            const stepLabel = panelArray[idx].querySelector('.step-label');
            if (stepLabel) {
              stepLabel.textContent = this.t('stepOf', { step: stepNum + 1, total: validOrder.length });
            }
        });

        const tabContainer = document.querySelector('.builder-tabs');
        if (tabContainer) {
            const tabArray = Array.from(this.tabs);
            tabContainer.innerHTML = '';
            validOrder.forEach((idx, stepNum) => {
                const tab = tabArray[idx];
                if (tab) {
                    const numSpan = tab.querySelector('.tab-num');
                    if (numSpan) numSpan.textContent = stepNum + 1;
                    tab.setAttribute('onclick', `Builder.switchSection(${stepNum})`);
                    tabContainer.appendChild(tab);
                }
            });
        }

        this.panels = document.querySelectorAll('.section-panel');
        this.tabs = document.querySelectorAll('.tab-btn');
    },

    bindEvents() {
        document.addEventListener('click', (e) => {
            if (e.target.closest('.remove-item-btn')) {
                this.removeFormsetItem(e.target.closest('.remove-item-btn'));
            }
        });

        this.form.addEventListener('change', () => {});

        this.form.addEventListener('submit', (e) => {
            const submitter = e.submitter || document.activeElement;

            if (!this.form.checkValidity()) {
                e.preventDefault();
                this.jumpToFirstInvalid();
                this.showToast(this.t('beforeLaunchErrors'), "error");
            } else {
                this.setSubmittingState(submitter);
                this.showToast(this.t('savingLaunch'), "success");
            }
        });
    },

    jumpToFirstInvalid() {
        const firstInvalid = this.form.querySelector(':invalid');
        if (firstInvalid) {
            const panel = firstInvalid.closest('.section-panel');
            if (panel) {
                const index = Array.from(this.panels).indexOf(panel);
                this.switchSection(index, true);
                setTimeout(() => {
                    firstInvalid.focus();
                    firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    firstInvalid.reportValidity();
                    firstInvalid.classList.add('error-pulse');
                    setTimeout(() => firstInvalid.classList.remove('error-pulse'), 2000);
                }, 100);
            } else {
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
            toast.style.cssText = 'position:fixed;bottom:2rem;left:50%;transform:translateX(-50%) translateY(5rem);z-index:99999;padding:0.75rem 1.5rem;border-radius:1rem;font-weight:700;font-size:0.875rem;box-shadow:0 20px 60px rgba(0,0,0,0.5);transition:all 0.3s cubic-bezier(0.4,0,0.2,1);opacity:0;white-space:nowrap;';
            document.body.appendChild(toast);
        }

        const styles = {
            success: 'background:rgba(34,197,94,0.95);color:#fff;border:1px solid rgba(74,222,128,0.5);',
            error: 'background:rgba(239,68,68,0.95);color:#fff;border:1px solid rgba(248,113,113,0.5);',
            info: 'background:rgba(59,130,246,0.95);color:#fff;border:1px solid rgba(96,165,250,0.5);'
        };

        toast.style.cssText += styles[type] || styles.success;
        toast.textContent = message;

        setTimeout(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(-50%) translateY(0)';
        }, 10);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(-50%) translateY(5rem)';
        }, type === 'error' ? 4000 : 3000);
    },

    setSubmittingState(submitter) {
        const btn = submitter && submitter.id ? submitter : document.getElementById('submit-btn');
        if (btn) {
            setTimeout(() => {
                btn.disabled = true;
                btn.innerHTML = `<div style="display:flex;align-items:center;gap:0.75rem;"><svg style="animation:spin 1s linear infinite;width:1.25rem;height:1.25rem;" viewBox="0 0 24 24"><circle style="opacity:0.25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path style="opacity:0.75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg><span>${this.t('launching')}</span></div>`;
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
            if (input.type === 'hidden' || input.closest('[style*="display: none"]')) return;

            if (!input.checkValidity()) {
                isValid = false;
                if (!firstInvalid) firstInvalid = input;
                input.classList.add('invalid-field');
            } else {
                input.classList.remove('invalid-field');
            }
        });

        if (!isValid && firstInvalid) {
            firstInvalid.reportValidity();
            firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            this.showToast(this.t('sectionRequired'), "error");
        }

        return isValid;
    },

    switchSection(index, bypassValidation = false) {
        if (index < 0 || index >= this.panels.length) return;

        if (!bypassValidation && index > this.currentSection) {
            for (let i = this.currentSection; i < index; i++) {
                if (!this.validateSection(i)) return;
            }
        }

        this.panels[this.currentSection].classList.remove('active');
        if (this.tabs[this.currentSection]) {
            this.tabs[this.currentSection].classList.remove('active');
        }

        this.currentSection = index;

        const nextPanel = this.panels[index];
        nextPanel.classList.add('active');
        if (this.tabs[index]) {
            this.tabs[index].classList.add('active');
        }

        this.tabs.forEach((tab, i) => {
            tab.classList.toggle('active', i === index);
            tab.classList.toggle('filled', i < index);
        });
        
        if (this.progressLabel) {
            if (this.tabs[index]) {
                const span = this.tabs[index].querySelector('span:not(.tab-num)');
                this.progressLabel.textContent = span ? span.textContent : this.tabs[index].textContent;
            } else {
                const header = nextPanel.querySelector('h2');
                if (header) this.progressLabel.textContent = header.textContent;
            }
        }

        const isMobile = window.matchMedia('(max-width: 768px)').matches;

        if (isMobile) {
            const tab = this.tabs[index];
            if (tab && tab.parentElement) {
                const container = tab.parentElement;
                container.scrollTo({
                    left: tab.offsetLeft - container.clientWidth / 2 + tab.clientWidth / 2,
                    behavior: 'smooth'
                });
            }
            const navHeight = (document.querySelector('nav') || { offsetHeight: 64 }).offsetHeight || 64;
            const panelTop = nextPanel.getBoundingClientRect().top + window.pageYOffset;
            window.scrollTo({ top: Math.max(0, panelTop - navHeight - 16), behavior: 'smooth' });
        } else {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    addFormsetItem(prefix) {
        const totalFormsInput = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
        const count = parseInt(totalFormsInput.value);
        const container = document.getElementById(`${prefix}-container`);
        
        const templateSource = document.getElementById(`${prefix}-empty-form`);
        if (!templateSource) {
            console.warn(`No empty-form template found for prefix: ${prefix}`);
            return;
        }

        let html = templateSource.innerHTML;
        html = html.replace(/__prefix__/g, count);

        const wrapper = document.createElement('div');
        wrapper.className = 'formset-item animate-slideIn';
        wrapper.innerHTML = html;

        if (!wrapper.querySelector('.remove-item-btn')) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'remove-item-btn';
            btn.innerHTML = '✕';
            wrapper.appendChild(btn);
        }

        container.prepend(wrapper);
        totalFormsInput.value = count + 1;

        this.setupImagePreviews();
    },

    removeFormsetItem(btn) {
        const item = btn.closest('.formset-item');
        const deleteCheckbox = item.querySelector('input[type="checkbox"][name$="-DELETE"]');
        
        if (deleteCheckbox) {
            deleteCheckbox.checked = true;
            item.style.display = 'none';
            item.querySelectorAll('[required]').forEach(el => el.removeAttribute('required'));
        } else {
            item.remove();
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
                    const item = input.closest('.formset-item') || input.closest('.glass-panel');
                    let previewBox = item ? item.querySelector('.preview-box') : null;
                    
                    if (!previewBox) {
                        previewBox = document.createElement('div');
                        previewBox.className = 'preview-box mt-4';
                        input.parentElement.appendChild(previewBox);
                    }
                    
                    previewBox.innerHTML = `<img src="${event.target.result}" alt="${this.t('imgAlt')}" class="w-full h-full object-cover">`;
                };
                reader.readAsDataURL(file);
            });
        });
    },

    checkInitialErrors() {
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

            document.querySelectorAll('.section-panel').forEach((p, i) => {
                if (p.querySelector('.error-msg')) {
                    this.tabs[i].classList.add('has-error');
                }
            });
        }
    },

    // ==========================================
    // CATEGORY MODAL & CHIPS LOGIC
    // ==========================================
    selectCategoryChip(btn) {
        const container = btn.closest('.category-chips-container');
        if (!container) return;

        // Deactivate all chips in this container
        container.querySelectorAll('.category-chip').forEach(chip => {
            chip.classList.remove('active');
        });

        // Activate the clicked chip
        btn.classList.add('active');

        // Update hidden input
        const hiddenInput = container.parentElement.querySelector('.project-category-input');
        if (hiddenInput) {
            hiddenInput.value = btn.dataset.value;
        }
    },

    openCategoryModalFor(btn) {
        const modal = document.getElementById('category-modal');
        const content = document.getElementById('category-modal-content');
        
        // Reset form fields for Creation state
        document.getElementById('cat-modal-id').value = '';
        document.getElementById('cat-modal-name').value = '';
        document.getElementById('cat-modal-desc').value = '';
        document.getElementById('cat-modal-thumb').value = '';
        document.getElementById('cat-thumb-preview').style.display = 'none';
        document.getElementById('cat-thumb-placeholder').style.display = 'flex';
        document.getElementById('cat-thumb-name').textContent = this.t('noFileChosen');
        document.getElementById('cat-modal-name-error').style.display = 'none';
        document.getElementById('cat-modal-name').style.borderColor = 'rgba(255,255,255,0.1)';
        document.getElementById('cat-modal-title').textContent = this.t('createCategory');
        
        // Show modal with animation
        modal.style.display = 'flex';
        setTimeout(() => {
            modal.style.opacity = '1';
            content.style.transform = 'scale(1)';
            content.style.opacity = '1';
            document.getElementById('cat-modal-name').focus();
        }, 10);

        // Close on backdrop click
        modal.onclick = (e) => { if (e.target === modal) this.closeCategoryModal(); };
    },

    editCategory(catId) {
        const card = document.querySelector(`.category-manager-card[data-category-id="${catId}"]`);
        if (!card) return;

        const modal = document.getElementById('category-modal');
        const content = document.getElementById('category-modal-content');

        // Pre-fill modal fields
        document.getElementById('cat-modal-id').value = catId;
        document.getElementById('cat-modal-name').value = card.dataset.name;
        document.getElementById('cat-modal-desc').value = card.dataset.description;
        document.getElementById('cat-modal-thumb').value = '';
        document.getElementById('cat-modal-name-error').style.display = 'none';
        document.getElementById('cat-modal-name').style.borderColor = 'rgba(255,255,255,0.1)';
        document.getElementById('cat-modal-title').textContent = this.t('editCategory');

        // Previews
        const preview = document.getElementById('cat-thumb-preview');
        const placeholder = document.getElementById('cat-thumb-placeholder');
        const nameSpan = document.getElementById('cat-thumb-name');

        if (card.dataset.thumbnailUrl) {
            preview.src = card.dataset.thumbnailUrl;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
            nameSpan.textContent = this.t('existingThumbnail');
        } else {
            preview.style.display = 'none';
            placeholder.style.display = 'flex';
            nameSpan.textContent = this.t('noFileChosen');
        }

        // Show modal
        modal.style.display = 'flex';
        setTimeout(() => {
            modal.style.opacity = '1';
            content.style.transform = 'scale(1)';
            content.style.opacity = '1';
            document.getElementById('cat-modal-name').focus();
        }, 10);

        modal.onclick = (e) => { if (e.target === modal) this.closeCategoryModal(); };
    },

    deleteCategory(catId) {
        if (!confirm(this.t('confirmDeleteCollection'))) {
            return;
        }

        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                          document.querySelector('meta[name="csrf-token"]')?.content;
        const deleteUrl = '/ajax/delete-category/'; // Explicit AJAX delete endpoint

        if (!csrfToken) {
            this.showToast(this.t('securityToken'), 'error');
            return;
        }

        const formData = new FormData();
        formData.append('id', catId);

        this.showToast(this.t('deletingCollection'), 'info');

        fetch(deleteUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData,
        })
        .then(res => res.json())
        .then(data => {
            if (!data.success) {
                this.showToast(data.error || this.t('failedDeleteCategory'), 'error');
                return;
            }

            // Remove card from manager grid
            const card = document.querySelector(`.category-manager-card[data-category-id="${catId}"]`);
            if (card) card.remove();

            // Check if grid is empty to toggle empty state
            const grid = document.getElementById('builder-categories-grid');
            if (grid && grid.querySelectorAll('.category-manager-card').length === 0) {
                let emptyState = document.getElementById('no-categories-state');
                if (!emptyState) {
                    emptyState = document.createElement('div');
                    emptyState.id = 'no-categories-state';
                    emptyState.className = 'col-span-full py-8 text-center border border-dashed border-white/5 rounded-xl text-zinc-500 text-xs';
                    emptyState.textContent = this.t('noCollections');
                    grid.appendChild(emptyState);
                } else {
                    emptyState.style.display = 'block';
                }
            }

            // Clean up chips across all project cards
            document.querySelectorAll('.category-chips-container').forEach(container => {
                const chip = container.querySelector(`.category-chip[data-value="${catId}"]`);
                if (chip) {
                    // If the project had this category active, reset it to Uncategorized
                    if (chip.classList.contains('active')) {
                        const uncategorizedChip = container.querySelector('.category-chip[data-value=""]');
                        if (uncategorizedChip) uncategorizedChip.click();
                    }
                    chip.remove();
                }
            });

            // Sync the empty-form template
            const templateSource = document.getElementById('projects-empty-form');
            if (templateSource) {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = templateSource.innerHTML;
                const chip = tempDiv.querySelector(`.category-chip[data-value="${catId}"]`);
                if (chip) {
                    chip.remove();
                    templateSource.innerHTML = tempDiv.innerHTML;
                }
            }

            this.showToast(this.t('collectionDeleted'), 'success');
        })
        .catch(err => {
            console.error('Delete AJAX error:', err);
            this.showToast(this.t('errorConnecting'), 'error');
        });
    },

    closeCategoryModal() {
        const modal = document.getElementById('category-modal');
        const content = document.getElementById('category-modal-content');
        
        modal.style.opacity = '0';
        content.style.transform = 'scale(0.95)';
        content.style.opacity = '0';
        setTimeout(() => {
            modal.style.display = 'none';
        }, 300);
    },

    handleCategoryThumbPreview(input) {
        const file = input.files[0];
        if (!file) return;
        
        const preview = document.getElementById('cat-thumb-preview');
        const placeholder = document.getElementById('cat-thumb-placeholder');
        const nameSpan = document.getElementById('cat-thumb-name');
        
        nameSpan.textContent = file.name;
        
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
    },

    saveCategoryModal() {
        const idInput = document.getElementById('cat-modal-id');
        const nameInput = document.getElementById('cat-modal-name');
        const descInput = document.getElementById('cat-modal-desc');
        const thumbInput = document.getElementById('cat-modal-thumb');
        const nameError = document.getElementById('cat-modal-name-error');
        const saveBtn = document.querySelector('[onclick="Builder.saveCategoryModal()"]');
        
        const catId = idInput.value;
        const name = nameInput.value.trim();
        
        if (!name) {
            nameError.style.display = 'block';
            nameInput.style.borderColor = 'rgba(248,113,113,0.6)';
            nameInput.focus();
            return;
        }
        nameError.style.display = 'none';

        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                          document.querySelector('meta[name="csrf-token"]')?.content;
        const url = document.getElementById('ajax-save-category-url')?.value;
        
        if (!url || !csrfToken) {
            console.error('Missing CSRF token or AJAX URL.');
            this.showToast(this.t('configError'), 'error');
            return;
        }
        
        const formData = new FormData();
        if (catId) {
            formData.append('id', catId);
        }
        formData.append('name', name);
        formData.append('description', descInput.value.trim());
        if (thumbInput.files && thumbInput.files[0]) {
            formData.append('thumbnail', thumbInput.files[0]);
        }
        
        // Loading state
        const originalHTML = saveBtn.innerHTML;
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="animation:spin 0.8s linear infinite;display:inline;vertical-align:middle;margin-right:4px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> ${this.t('saving')}`;
        
        fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData,
        })
        .then(res => res.json())
        .then(data => {
            if (!data.success) {
                this.showToast(data.error || this.t('failedSaveCategory'), 'error');
                return;
            }
            
            if (data.created) {
                // Remove empty state from manager grid if present
                const emptyState = document.getElementById('no-categories-state');
                if (emptyState) emptyState.remove();

                // Append new card to the manager grid
                const grid = document.getElementById('builder-categories-grid');
                if (grid) {
                    const card = document.createElement('div');
                    card.className = 'category-manager-card group relative p-4 rounded-xl border border-white/5 bg-zinc-950/40 hover:border-violet-500/40 transition-all flex flex-col justify-between min-h-[140px]';
                    card.setAttribute('data-category-id', data.id);
                    card.setAttribute('data-name', data.name);
                    card.setAttribute('data-description', data.description);
                    card.setAttribute('data-thumbnail-url', data.thumbnail_url || '');

                    let imgTag = '';
                    if (data.thumbnail_url) {
                        imgTag = `<img src="${data.thumbnail_url}" class="cat-card-bg w-full h-full object-cover opacity-20 filter blur-sm group-hover:scale-105 transition-all">`;
                    }

                    card.innerHTML = `
                      <!-- Cover Thumbnail Overlay Background -->
                      <div class="absolute inset-0 rounded-xl overflow-hidden z-0">
                        ${imgTag}
                        <div class="absolute inset-0 bg-gradient-to-t from-zinc-950 via-zinc-950/80 to-transparent"></div>
                      </div>

                      <!-- Actions -->
                      <div class="relative z-10 flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button type="button" class="w-7 h-7 rounded-lg bg-zinc-900 border border-white/10 text-zinc-400 hover:text-white flex items-center justify-center text-xs" onclick="Builder.editCategory('${data.id}')" title="${this.t('editCollection')}">
                          <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
                        </button>
                        <button type="button" class="w-7 h-7 rounded-lg bg-zinc-900 border border-white/10 text-red-400 hover:text-red-300 flex items-center justify-center text-xs" onclick="Builder.deleteCategory('${data.id}')" title="${this.t('deleteCollection')}">
                          <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-7v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        </button>
                      </div>

                      <!-- Details -->
                      <div class="relative z-10 mt-auto">
                        <h4 class="text-sm font-bold text-white cat-card-title">${data.name}</h4>
                        <p class="text-[10px] text-zinc-500 mt-1 line-clamp-2 cat-card-desc">${data.description}</p>
                      </div>
                    `;
                    grid.appendChild(card);
                }

                // Append new chip to all project cards
                document.querySelectorAll('.category-chips-container').forEach(container => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'category-chip';
                    btn.setAttribute('data-value', data.id);
                    btn.setAttribute('onclick', 'Builder.selectCategoryChip(this)');
                    btn.textContent = data.name;
                    container.appendChild(btn);
                });

                // Sync the empty-form template
                const templateSource = document.getElementById('projects-empty-form');
                if (templateSource) {
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = templateSource.innerHTML;
                    const container = tempDiv.querySelector('.category-chips-container');
                    if (container) {
                        const btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'category-chip';
                        btn.setAttribute('data-value', data.id);
                        btn.setAttribute('onclick', 'Builder.selectCategoryChip(this)');
                        btn.textContent = data.name;
                        container.appendChild(btn);
                        templateSource.innerHTML = tempDiv.innerHTML;
                    }
                }

                this.showToast(this.t('collectionCreated', { name: data.name }), 'success');
            } else {
                // Update existing card in manager grid
                const card = document.querySelector(`.category-manager-card[data-category-id="${data.id}"]`);
                if (card) {
                    card.setAttribute('data-name', data.name);
                    card.setAttribute('data-description', data.description);
                    if (data.thumbnail_url) {
                        card.setAttribute('data-thumbnail-url', data.thumbnail_url);
                        // Update background image image tag
                        let bgContainer = card.querySelector('.absolute.z-0');
                        if (bgContainer) {
                            let img = bgContainer.querySelector('.cat-card-bg');
                            if (!img) {
                                img = document.createElement('img');
                                img.className = 'cat-card-bg w-full h-full object-cover opacity-20 filter blur-sm group-hover:scale-105 transition-all';
                                bgContainer.insertBefore(img, bgContainer.firstChild);
                            }
                            img.src = data.thumbnail_url;
                        }
                    }

                    const title = card.querySelector('.cat-card-title');
                    if (title) title.textContent = data.name;

                    const desc = card.querySelector('.cat-card-desc');
                    if (desc) desc.textContent = data.description;
                }

                // Update text of corresponding chips in all project cards
                document.querySelectorAll(`.category-chip[data-value="${data.id}"]`).forEach(chip => {
                    chip.textContent = data.name;
                });

                // Sync the empty-form template
                const templateSource = document.getElementById('projects-empty-form');
                if (templateSource) {
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = templateSource.innerHTML;
                    const chip = tempDiv.querySelector(`.category-chip[data-value="${data.id}"]`);
                    if (chip) {
                        chip.textContent = data.name;
                        templateSource.innerHTML = tempDiv.innerHTML;
                    }
                }

                this.showToast(this.t('collectionUpdated', { name: data.name }), 'success');
            }
            
            this.closeCategoryModal();
        })
        .catch(err => {
            console.error('AJAX error:', err);
            this.showToast(this.t('networkError'), 'error');
        })
        .finally(() => {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalHTML;
        });
    },

    toggleReview(reviewId, btn) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                          document.querySelector('meta[name="csrf-token"]')?.content;
        if (!csrfToken) {
            this.showToast(this.t('securityToken'), 'error');
            return;
        }

        const formData = new FormData();
        formData.append('next', window.location.pathname + window.location.search);

        fetch(`/dashboard/reviews/${reviewId}/toggle/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData,
        })
        .then(res => {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const card = document.querySelector(`.review-card[data-review-id="${reviewId}"]`);
            if (!card) return;

            const featured = card.dataset.featured === '1';
            card.dataset.featured = featured ? '0' : '1';
            const listed = !featured;

            const badge = card.querySelector('.review-badge');
            if (badge) {
                badge.textContent = listed
                    ? (badge.dataset.listedLabel || 'Listed on Portfolio')
                    : (badge.dataset.pendingLabel || 'Pending');
                badge.className = 'review-badge px-2.5 py-1 rounded-full text-[10px] font-bold ' +
                    (listed
                        ? 'bg-emerald-50 border border-emerald-500/30 text-emerald-700'
                        : 'bg-amber-50 border border-amber-500/30 text-amber-600');
            }

            if (btn) {
                btn.textContent = listed
                    ? (btn.dataset.removeLabel || 'Remove from Portfolio')
                    : (btn.dataset.listLabel || 'List on Portfolio');
                btn.className = 'review-toggle-btn inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all ' +
                    (listed
                        ? 'border border-red-500/30 text-red-600 hover:bg-red-50'
                        : 'bg-emerald-600 hover:bg-emerald-700 text-white');
            }

            this.showToast(this.t(listed ? 'reviewListed' : 'reviewHidden'), 'success');
        })
        .catch(err => {
            console.error('AJAX error:', err);
            this.showToast(this.t('networkError'), 'error');
        });
    }
};

// Spinner keyframe (injected once)
const _spinStyle = document.createElement('style');
_spinStyle.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
document.head.appendChild(_spinStyle);

document.addEventListener('DOMContentLoaded', () => Builder.init());
