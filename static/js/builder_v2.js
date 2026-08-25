const BX_I18N = Object.assign({
  secIdentity: 'Personal identity',
  secSkills: 'Skills',
  secEducation: 'Education',
  secExperience: 'Experience',
  secProjects: 'Projects',
  secLinks: 'Links',
  secCreators: 'Creators',
  secReviews: 'Client reviews',
  kickerPrefix: 'Section {n}',
  progressOf: '{done} of {total} sections complete',
  charsCount: '{n} characters',
  msgStepAttention: 'Some fields in this section need attention — you can keep going, we will flag them before saving.',
  msgFixBeforeLaunch: 'Please fix the highlighted fields before launching.',
  fieldGeneric: 'Please check this field.',
  fieldPhone: 'Enter a valid phone number.',
  fieldEmail: 'Enter a valid email address.',
  savingOverlay: 'Saving your portfolio…',
  savingBtn: ' Saving…',
  noFile: 'No file chosen',
  msgRemoved: 'Removed — click undo to restore.',
  undo: 'Undo',
  msgRestored: 'Restored.',
  modalEditTitle: 'Edit collection',
  modalNewTitle: 'New collection',
  coverCurrent: 'Current cover — uploading replaces it',
  emptyCollectionsTitle: 'No collections yet',
  emptyCollectionsSub: 'Without collections, all videos display under "Other Videos".',
  confirmDeleteCollection: 'Delete this collection? Projects inside it become Uncategorized.',
  msgConfigError: 'Configuration error — please refresh and try again.',
  msgSaveCategoryFail: 'Failed to save collection.',
  msgCategoryCreated: 'Collection "{name}" created!',
  msgCategoryUpdated: 'Collection "{name}" updated.',
  msgDeleteCategoryFail: 'Failed to delete collection.',
  msgCategoryDeleted: 'Collection deleted.',
  msgNetworkError: 'Network error — please try again.',
  msgServerError: 'Error connecting to server.',
  msgTokenMissing: 'Security token not found. Please reload.',
  badgeListed: 'Listed on portfolio',
  badgePending: 'Pending',
  btnRemoveFromPortfolio: 'Remove from portfolio',
  btnListOnPortfolio: 'List on portfolio',
  msgReviewLive: 'Review is now live on your portfolio.',
  msgReviewHidden: 'Review hidden from your portfolio.'
}, window.BuilderI18n || {});

function bxt(key, vars) {
  let str = BX_I18N[key] || key;
  if (vars) {
    Object.keys(vars).forEach(k => {
      str = str.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
    });
  }
  return str;
}

const BX = {
  currentKey: 'identity',
  isDirty: false,
  isSubmitting: false,
  undoStack: [],
  lastSubmitter: null,
  order: ['identity', 'skills', 'education', 'experience', 'projects', 'links', 'creators', 'reviews'],

  ORDERS_BY_CATEGORY: {
    student: ['identity', 'education', 'skills', 'experience', 'projects', 'creators', 'reviews', 'links'],
    video_editor: ['identity', 'projects', 'skills', 'creators', 'reviews', 'experience', 'education', 'links'],
    developer: ['identity', 'skills', 'experience', 'projects', 'creators', 'reviews', 'education', 'links']
  },

  SECTION_LABELS: {
    identity: bxt('secIdentity'),
    skills: bxt('secSkills'),
    education: bxt('secEducation'),
    experience: bxt('secExperience'),
    projects: bxt('secProjects'),
    links: bxt('secLinks'),
    creators: bxt('secCreators'),
    reviews: bxt('secReviews')
  },

  ACTIONABLE_SECTIONS: ['identity', 'skills', 'education', 'experience', 'projects', 'links', 'creators'],

  init() {
    this.root = document.getElementById('builder-root');
    if (!this.root) return;
    this.category = (this.root.dataset.category || 'developer').trim().toLowerCase().replace(/\s+/g, '_');
    this.form = document.getElementById('portfolio-form');
    this.panelsWrap = document.getElementById('bx-panels');
    this.navList = document.getElementById('bx-nav');

    this.cachePanels();
    this.applySectionOrder();
    this.bindEvents();
    this.setupCharCounters();
    this.refreshEmptyStates();
    this.refreshProgress();
    this.openFromHash();
    this.updateNavStates();
  },

  cachePanels() {
    this.panels = Array.from(this.panelsWrap.querySelectorAll('.bx-panel'));
    this.panelByKey = {};
    this.panels.forEach(p => { this.panelByKey[p.dataset.key] = p; });
    this.navItems = Array.from(this.navList.querySelectorAll('.bx-nav-item'));
    this.navByKey = {};
    this.navItems.forEach(n => { this.navByKey[n.dataset.navKey] = n; });
  },

  applySectionOrder() {
    const preferred = this.ORDERS_BY_CATEGORY[this.category] || this.ORDERS_BY_CATEGORY.developer;
    const valid = preferred.filter(k => this.panelByKeyExists(k));
    if (valid.length !== preferred.length || valid.length !== this.panels.length) return;

    this.order = valid;
    valid.forEach((key, i) => {
      const panel = document.getElementById('panel-' + key);
      if (panel) {
        const kicker = panel.querySelector('.bx-panel-kicker');
        if (kicker) kicker.textContent = bxt('kickerPrefix', { n: i + 1 });
        this.panelsWrap.appendChild(panel);
      }
      const navBtn = this.navByKey ? this.navByKey[key] : null;
      if (navBtn) {
        const num = navBtn.querySelector('.bx-nav-num');
        if (num) num.textContent = i + 1;
        const navLi = navBtn.closest('li');
        if (navLi) this.navList.appendChild(navLi);
      }
    });
    this.panels = Array.from(this.panelsWrap.querySelectorAll('.bx-panel'));
    this.navItems = Array.from(this.navList.querySelectorAll('.bx-nav-item'));
    this.updateFooterButtons();
  },

  updateFooterButtons() {
    const lastKey = this.order[this.order.length - 1];
    this.order.forEach(key => {
      const panel = this.panelByKey[key];
      if (!panel) return;
      const nextBtn = panel.querySelector('[data-nav-next]');
      const saveBtn = panel.querySelector('[data-nav-save]');
      const isLast = key === lastKey;
      if (nextBtn) nextBtn.hidden = isLast;
      if (saveBtn) saveBtn.hidden = !isLast;
    });
  },

  panelByKeyExists(key) {
    return !!document.getElementById('panel-' + key);
  },

  bindEvents() {
    this.navList.addEventListener('click', (e) => {
      const btn = e.target.closest('.bx-nav-item');
      if (btn) this.goTo(btn.dataset.navKey);
    });

    document.addEventListener('click', (e) => {
      const actionEl = e.target.closest('[data-action]');
      if (!actionEl) {
        const chip = e.target.closest('.category-chips-container .bx-chip');
        if (chip) this.selectChip(chip);
        return;
      }
      const action = actionEl.dataset.action;
      switch (action) {
        case 'next': this.step(1); break;
        case 'prev': this.step(-1); break;
        case 'add': this.addItem(actionEl.dataset.prefix); break;
        case 'remove-item': this.removeItem(actionEl); break;
        case 'open-category-modal': this.openCategoryModal(null, actionEl); break;
        case 'edit-category': this.editCategory(actionEl.dataset.categoryId, actionEl); break;
        case 'delete-category': this.deleteCategory(actionEl.dataset.categoryId); break;
        case 'close-category-modal': this.closeCategoryModal(); break;
        case 'save-category-modal': this.saveCategoryModal(); break;
        case 'toggle-review': this.toggleReview(actionEl.dataset.reviewId, actionEl); break;
        case 'clear-upload': this.clearUpload(actionEl); break;
      }
    });

    document.addEventListener('click', (e) => {
      const saver = e.target.closest('[data-save-button]');
      if (saver && this.form.contains(saver) || saver && saver.getAttribute('form') === 'portfolio-form') {
        this.lastSubmitter = saver;
      }
    });

    this.form.addEventListener('input', () => this.markDirty());
    this.form.addEventListener('change', (e) => {
      this.markDirty();
      if (e.target.matches('input[type="file"]')) this.handleFileChange(e.target);
    });

    this.form.addEventListener('focusout', (e) => {
      const field = e.target;
      if (!field.matches('input, textarea, select')) return;
      if (field.type === 'file' || field.type === 'hidden') return;
      if (this.isSubmitting) return;
      if (this.isRowPristineEmpty(field)) return;
      if (field.value || field.classList.contains('was-touched')) {
        field.classList.add('was-touched');
        this.validateField(field);
      }
    });

    this.form.addEventListener('submit', (e) => this.handleSubmit(e));

    window.addEventListener('beforeunload', (e) => {
      if (this.isDirty && !this.isSubmitting) {
        e.preventDefault();
        e.returnValue = '';
        return e.returnValue;
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('category-modal');
        if (modal.classList.contains('is-open')) {
          this.closeCategoryModal();
          return;
        }
      }
    });

    document.addEventListener('dragover', (e) => {
      const zone = e.target.closest('.bx-dropzone');
      if (!zone) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      zone.classList.add('is-dragover');
    });

    document.addEventListener('dragleave', (e) => {
      const zone = e.target.closest('.bx-dropzone');
      if (zone && (!e.relatedTarget || !zone.contains(e.relatedTarget))) {
        zone.classList.remove('is-dragover');
      }
    });

    document.addEventListener('drop', (e) => {
      const zone = e.target.closest('.bx-dropzone');
      if (!zone) return;
      e.preventDefault();
      zone.classList.remove('is-dragover');
      const input = zone.querySelector('input[type="file"]');
      if (input && e.dataTransfer && e.dataTransfer.files.length) {
        try { input.files = e.dataTransfer.files; } catch (err) { return; }
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });

    const modalName = document.getElementById('cat-modal-name');
    if (modalName) {
      modalName.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.saveCategoryModal();
        }
      });
    }
  },

  goTo(key) {
    const panel = this.panelByKey[key];
    if (!panel || key === this.currentKey) return;

    const current = this.panelByKey[this.currentKey];
    if (current) current.classList.remove('is-active');
    panel.classList.add('is-active');

    this.navItems.forEach(n => {
      const active = n.dataset.navKey === key;
      n.classList.toggle('is-active', active);
      if (active) n.setAttribute('aria-current', 'true');
      else n.removeAttribute('aria-current');
    });

    this.currentKey = key;
    history.replaceState(null, '', '#' + key);

    const mobile = window.matchMedia('(max-width: 1023px)').matches;
    if (mobile) {
      const navBtn = this.navByKey[key];
      if (navBtn && this.navList) {
        const list = this.navList;
        const targetLeft = navBtn.offsetLeft - list.clientWidth / 2 + navBtn.clientWidth / 2;
        const currentLeft = list.scrollLeft;
        if (Math.abs(targetLeft - currentLeft) > 4) {
          list.scrollTo({ left: targetLeft, behavior: 'auto' });
        }
      }
    }

    const navH = 64;
    let extraOffset = 20;
    if (mobile) {
      const sidebarEl = document.querySelector('.bx-sidebar');
      extraOffset = (sidebarEl ? sidebarEl.offsetHeight : 56) + 12;
    }
    const top = panel.getBoundingClientRect().top + window.pageYOffset - navH - extraOffset;
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    panel.focus({ preventScroll: true });
  },

  step(delta) {
    const idx = this.order.indexOf(this.currentKey);
    const next = this.order[idx + delta];
    if (!next) return;
    if (delta > 0) {
      const result = this.validatePanel(this.currentKey, true);
      if (!result.valid) {
        this.toast(bxt('msgStepAttention'), 'info');
      }
    }
    this.goTo(next);
  },

  validateField(field) {
    const wrap = field.closest('.bx-field');
    if (!wrap) return true;
    const errEl = wrap.querySelector('.bx-field-error');
    const isValid = field.checkValidity();

    field.removeAttribute('aria-invalid');
    field.removeAttribute('aria-describedby');
    if (errEl) {
      errEl.classList.remove('is-visible');
      errEl.textContent = '';
    }
    wrap.classList.remove('has-error');

    if (!isValid) {
      field.setAttribute('aria-invalid', 'true');
      if (errEl) {
        let msg = field.validationMessage || bxt('fieldGeneric');
        if (field.validity.patternMismatch && field.type === 'tel') msg = bxt('fieldPhone');
        if (field.validity.typeMismatch && field.type === 'email') msg = bxt('fieldEmail');
        errEl.textContent = msg;
        errEl.id = errEl.id || 'err-' + Math.random().toString(36).slice(2, 8);
        field.setAttribute('aria-describedby', errEl.id);
        errEl.classList.add('is-visible');
      }
      wrap.classList.add('has-error');
      return false;
    }
    return true;
  },

  isVisibleInPanel(panel, field) {
    if (field.type === 'hidden') return false;
    let node = field;
    while (node && node !== panel) {
      const style = node.style || {};
      const inlineDisplay = (style.display || '').replace(/\s/g, '').toLowerCase();
      if (inlineDisplay === 'none') return false;
      if (node.getAttribute && node.getAttribute('aria-hidden') === 'true') return false;
      node = node.parentElement;
    }
    return true;
  },

  isRowPristineEmpty(field) {
    const item = field.closest('.bx-item');
    if (!item) return false;
    if (item.classList.contains('is-removed')) return true;
    if ((field.value || '').trim() !== '') return false;
    const controls = item.querySelectorAll('input:not([type="hidden"]), textarea, select');
    for (const control of controls) {
      if (control.type === 'checkbox') continue;
      if (control.type === 'file') {
        if (control.files && control.files.length) return false;
        continue;
      }
      if ((control.value || '').trim() !== '') return false;
    }
    return true;
  },

  validatePanel(key, quiet) {
    const panel = this.panelByKey[key];
    if (!panel) return { valid: true, count: 0, first: null };
    let count = 0;
    let first = null;

    panel.querySelectorAll('input, textarea, select').forEach(field => {
      if ((field.type === 'file' || field.type === 'hidden') && !field.required) return;
      if (field.disabled) return;
      if (!this.isVisibleInPanel(panel, field)) return;
      if (field.required && this.isRowPristineEmpty(field)) return;
      const ok = field.checkValidity();
      if (!ok) {
        count++;
        if (!first) first = field;
        if (!quiet) this.validateField(field);
      } else if (!quiet && field.closest('.bx-field')?.classList.contains('has-error')) {
        this.validateField(field);
      }
    });

    if (!quiet && first) {
      first.focus({ preventScroll: true });
      first.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    return { valid: count === 0, count, first };
  },

  handleSubmit(e) {
    if (this.isSubmitting) {
      e.preventDefault();
      return;
    }

    let totalErrors = 0;
    let firstBadKey = null;
    const errorMap = {};

    this.order.forEach(key => {
      const r = this.validatePanel(key, true);
      errorMap[key] = r.count;
      totalErrors += r.count;
      if (r.count > 0 && !firstBadKey) firstBadKey = key;
    });

    Object.keys(errorMap).forEach(key => {
      const nav = this.navByKey[key];
      if (nav) {
        nav.classList.toggle('is-error', errorMap[key] > 0);
        const state = nav.querySelector('.bx-nav-state');
        state.textContent = errorMap[key] > 0 ? String(errorMap[key]) : '';
      }
    });
    this.updateNavStates();

    if (totalErrors > 0) {
      e.preventDefault();
      this.toast(bxt('msgFixBeforeLaunch'), 'error');
      if (firstBadKey !== this.currentKey) this.goTo(firstBadKey);
      setTimeout(() => {
        const r = this.validatePanel(firstBadKey, false);
        if (r.first) {
          r.first.scrollIntoView({ behavior: 'smooth', block: 'center' });
          r.first.focus({ preventScroll: true });
        }
      }, 250);
      return;
    }

    this.isSubmitting = true;
    const label = document.getElementById('bx-saving-label');
    if (label) label.textContent = bxt('savingOverlay');
    document.getElementById('bx-saving-overlay').classList.add('is-open');

    const btn = e.submitter || this.lastSubmitter;
    if (btn) {
      setTimeout(() => {
        btn.disabled = true;
        btn.innerHTML = '<span class="bx-saving-spinner" style="width:16px;height:16px;border-width:2px;"></span>' + bxt('savingBtn');
      }, 0);
    }
  },

  markDirty() {
    if (this.isDirty) return;
    this.isDirty = true;
    document.body.classList.add('bx-is-dirty');
  },

  setupCharCounters() {
    document.querySelectorAll('[data-char-counter]').forEach(ta => {
      const counter = ta.parentElement.querySelector('.bx-char-count');
      if (!counter) return;
      const update = () => {
        const len = ta.value.length;
        counter.textContent = bxt('charsCount', { n: len });
      };
      ta.addEventListener('input', update);
      update();
    });
  },

  handleFileChange(input) {
    const upload = input.closest('.bx-upload');
    if (!upload) return;
    const preview = upload.querySelector('.bx-upload-preview');
    const nameEl = upload.querySelector('.bx-upload-name');
    const clearBtn = upload.querySelector('.bx-upload-clear');
    const file = input.files[0];

    if (file) {
      if (nameEl) nameEl.textContent = file.name;
      if (clearBtn) clearBtn.hidden = false;
      if (preview) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          preview.src = ev.target.result;
          preview.hidden = false;
        };
        reader.readAsDataURL(file);
      }
    } else {
      this.resetUploadMeta(upload);
    }
  },

  clearUpload(btn) {
    const upload = btn.closest('.bx-upload');
    if (!upload) return;
    const input = upload.querySelector('input[type="file"]');
    if (input) {
      input.value = '';
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    this.markDirty();
  },

  resetUploadMeta(upload) {
    if (!upload) return;
    const preview = upload.querySelector('.bx-upload-preview');
    const nameEl = upload.querySelector('.bx-upload-name');
    const clearBtn = upload.querySelector('.bx-upload-clear');
    if (preview) {
      preview.removeAttribute('src');
      preview.hidden = true;
    }
    if (nameEl) nameEl.textContent = bxt('noFile');
    if (clearBtn) clearBtn.hidden = true;
  },

  addItem(prefix) {
    const template = document.getElementById(prefix + '-empty-form');
    const container = document.getElementById(prefix + '-container');
    const totalForms = document.getElementById('id_' + prefix + '-TOTAL_FORMS');
    if (!template || !container || !totalForms) return;

    const count = parseInt(totalForms.value, 10);
    const wrapper = document.createElement('div');
    wrapper.className = 'bx-item';
    wrapper.innerHTML = template.innerHTML.replace(/__prefix__/g, count);

    container.prepend(wrapper);
    totalForms.value = count + 1;

    this.refreshEmptyStates();
    this.markDirty();
    this.updateNavStates();

    const firstInput = wrapper.querySelector('input:not([type=hidden]):not([type=file]), textarea');
    if (firstInput) {
      firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => firstInput.focus({ preventScroll: true }), 300);
    }
  },

  removeItem(btn) {
    const item = btn.closest('.bx-item');
    if (!item) return;

    const deleteCheckbox = item.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (!deleteCheckbox) {
      item.remove();
      this.afterRemoval();
      return;
    }

    const requiredFields = [];
    item.querySelectorAll('[required]').forEach(f => {
      requiredFields.push({ el: f, value: f.getAttribute('required') });
      f.removeAttribute('required');
    });

    deleteCheckbox.checked = true;
    item.classList.add('is-removed');
    setTimeout(() => { item.style.display = 'none'; }, 200);

    const entry = { item, deleteCheckbox, requiredFields };
    this.undoStack.push(entry);
    this.toast(bxt('msgRemoved'), 'info', {
      label: bxt('undo'),
      fn: () => this.restoreItem(entry)
    });
    this.afterRemoval();
  },

  restoreItem(entry) {
    entry.deleteCheckbox.checked = false;
    entry.item.style.display = '';
    requestAnimationFrame(() => entry.item.classList.remove('is-removed'));
    entry.requiredFields.forEach(r => r.el.setAttribute('required', r.value));
    this.undoStack = this.undoStack.filter(e => e !== entry);
    this.afterRemoval();
    this.toast(bxt('msgRestored'), 'success');
  },

  afterRemoval() {
    this.refreshEmptyStates();
    this.updateNavStates();
    this.markDirty();
  },

  refreshEmptyStates() {
    document.querySelectorAll('[data-empty-for]').forEach(empty => {
      const prefix = empty.dataset.emptyFor;
      const container = document.getElementById(prefix + '-container');
      if (!container) return;
      const hasVisible = Array.from(container.children).some(child =>
        child.classList.contains('bx-item') && !child.classList.contains('is-removed')
      );
      empty.hidden = hasVisible;
    });
  },

  updateNavStates() {
    this.order.forEach(key => {
      const nav = this.navByKey[key];
      if (!nav || nav.classList.contains('is-error')) return;
      const done = this.isSectionDone(key);
      nav.classList.toggle('is-done', done);
      const state = nav.querySelector('.bx-nav-state');
      if (done && !state.textContent) {
        state.innerHTML = '<svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="3" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
      } else if (!done) {
        state.innerHTML = '';
      }
    });
    this.refreshProgress();
  },

  isSectionDone(key) {
    const panel = this.panelByKey[key];
    if (!panel) return false;
    switch (key) {
      case 'identity':
        return ['fullname', 'title'].every(name => {
          const f = panel.querySelector('[name="' + name + '"]');
          return f && f.value.trim();
        });
      case 'reviews': {
        const listed = document.querySelector('.bx-review-card[data-featured="1"]');
        return !!listed;
      }
      default: {
        const containerId = key + '-container';
        const container = document.getElementById(containerId);
        if (!container) return false;
        const coreFields = {
          skills: '[name$="-skill"]',
          education: '[name$="-school"]',
          experience: '[name$="-title"]',
          projects: '[name$="-name"]',
          links: '[name$="-name"]',
          creators: '[name$="-name"]'
        };
        const selector = coreFields[key];
        if (!selector) return false;
        return Array.from(container.querySelectorAll(selector)).some(inp => {
          if (inp.name.endsWith('-DELETE')) return false;
          const item = inp.closest('.bx-item');
          if (item && (item.classList.contains('is-removed') || item.style.display === 'none')) return false;
          return inp.value.trim().length > 0;
        });
      }
    }
  },

  refreshProgress() {
    const fill = document.getElementById('bx-progress-fill');
    const label = document.getElementById('bx-progress-label');
    if (!fill || !label) return;
    const done = this.ACTIONABLE_SECTIONS.filter(k => this.isSectionDone(k)).length;
    const total = this.ACTIONABLE_SECTIONS.length;
    const pct = Math.round((done / total) * 100);
    fill.style.width = pct + '%';
    label.textContent = bxt('progressOf', { done: done, total: total });
  },

  selectChip(chip) {
    const container = chip.closest('.category-chips-container');
    if (!container) return;
    container.querySelectorAll('.bx-chip').forEach(c => c.classList.remove('is-active'));
    chip.classList.add('is-active');
    const hidden = chip.closest('.bx-item').querySelector('.project-category-input');
    if (hidden) hidden.value = chip.dataset.value;
    this.markDirty();
  },

  openCategoryModal(catData, opener) {
    const modal = document.getElementById('category-modal');
    const idInput = document.getElementById('cat-modal-id');
    const nameInput = document.getElementById('cat-modal-name');
    const descInput = document.getElementById('cat-modal-desc');
    const thumbInput = document.getElementById('cat-modal-thumb');
    const preview = document.getElementById('cat-thumb-preview');
    const nameSpan = document.getElementById('cat-thumb-name');
    const title = document.getElementById('cat-modal-title');
    const nameError = document.getElementById('cat-modal-name-error');

    this.catModalOpener = opener || null;

    if (catData) {
      idInput.value = catData.id;
      nameInput.value = catData.name;
      descInput.value = catData.description;
      title.textContent = bxt('modalEditTitle');
      if (catData.thumbnailUrl) {
        preview.src = catData.thumbnailUrl;
        preview.hidden = false;
        nameSpan.textContent = bxt('coverCurrent');
      } else {
        preview.hidden = true;
        nameSpan.textContent = bxt('noFile');
      }
    } else {
      idInput.value = '';
      nameInput.value = '';
      descInput.value = '';
      title.textContent = bxt('modalNewTitle');
      preview.hidden = true;
      nameSpan.textContent = bxt('noFile');
    }
    thumbInput.value = '';
    nameError.classList.remove('is-visible');

    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    setTimeout(() => nameInput.focus(), 60);

    modal.onclick = (e) => { if (e.target === modal) this.closeCategoryModal(); };

    this.trapFocus(modal);
  },

  editCategory(catId, opener) {
    const card = document.querySelector('.bx-cat-card[data-category-id="' + catId + '"]');
    if (!card) return;
    this.openCategoryModal({
      id: catId,
      name: card.dataset.name,
      description: card.dataset.description,
      thumbnailUrl: card.dataset.thumbnailUrl
    }, opener);
  },

  trapFocus(modal) {
    const focusables = () => Array.from(modal.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )).filter(el => !el.disabled && el.offsetParent !== null);

    modal.onkeydown = (e) => {
      if (e.key !== 'Tab') return;
      const els = focusables();
      if (!els.length) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
  },

  closeCategoryModal() {
    const modal = document.getElementById('category-modal');
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    modal.onclick = null;
    modal.onkeydown = null;
    if (this.catModalOpener) {
      this.catModalOpener.focus();
      this.catModalOpener = null;
    }
  },

  saveCategoryModal() {
    const idInput = document.getElementById('cat-modal-id');
    const nameInput = document.getElementById('cat-modal-name');
    const descInput = document.getElementById('cat-modal-desc');
    const thumbInput = document.getElementById('cat-modal-thumb');
    const nameError = document.getElementById('cat-modal-name-error');
    const saveBtn = document.querySelector('[data-action="save-category-modal"]');

    const catId = idInput.value;
    const name = nameInput.value.trim();

    if (!name) {
      nameError.classList.add('is-visible');
      nameInput.setAttribute('aria-invalid', 'true');
      nameInput.focus();
      return;
    }
    nameError.classList.remove('is-visible');
    nameInput.removeAttribute('aria-invalid');

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content;
    const url = document.getElementById('ajax-save-category-url')?.value;

    if (!url || !csrfToken) {
      this.toast(bxt('msgConfigError'), 'error');
      return;
    }

    const formData = new FormData();
    if (catId) formData.append('id', catId);
    formData.append('name', name);
    formData.append('description', descInput.value.trim());
    if (thumbInput.files && thumbInput.files[0]) formData.append('thumbnail', thumbInput.files[0]);

    const originalHTML = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="bx-saving-spinner" style="width:14px;height:14px;border-width:2px;"></span>' + bxt('savingBtn');

    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken },
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          this.toast(data.error || bxt('msgSaveCategoryFail'), 'error');
          return;
        }
        if (data.created) {
          this.addCategoryCard(data);
          this.addChipsEverywhere(data);
          this.syncProjectTemplate(data, 'add');
          this.toast(bxt('msgCategoryCreated', { name: data.name }), 'success');
        } else {
          this.updateCategoryCard(data);
          document.querySelectorAll('.category-chip[data-value="' + data.id + '"], .bx-chip[data-value="' + data.id + '"]').forEach(chip => {
            chip.textContent = data.name;
          });
          this.syncProjectTemplate(data, 'rename');
          this.toast(bxt('msgCategoryUpdated', { name: data.name }), 'success');
        }
        this.closeCategoryModal();
      })
      .catch(() => {
        this.toast(bxt('msgNetworkError'), 'error');
      })
      .finally(() => {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalHTML;
      });
  },

  addCategoryCard(data) {
    const grid = document.getElementById('builder-categories-grid');
    if (!grid) return;
    const emptyState = document.getElementById('no-categories-state');
    if (emptyState) emptyState.remove();

    const card = document.createElement('div');
    card.className = 'bx-cat-card';
    card.setAttribute('data-category-id', data.id);
    card.setAttribute('data-name', data.name);
    card.setAttribute('data-description', data.description);
    card.setAttribute('data-thumbnail-url', data.thumbnail_url || '');

    const imgTag = data.thumbnail_url
      ? '<img src="' + data.thumbnail_url + '" alt="" class="bx-cat-bg">'
      : '';

    card.innerHTML =
      imgTag +
      '<div class="bx-cat-actions">' +
        '<button type="button" class="bx-cat-action" data-action="edit-category" data-category-id="' + data.id + '" aria-label="Edit collection">' +
          '<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z"/></svg>' +
        '</button>' +
        '<button type="button" class="bx-cat-action is-danger" data-action="delete-category" data-category-id="' + data.id + '" aria-label="Delete collection">' +
          '<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/></svg>' +
        '</button>' +
      '</div>' +
      '<h4 class="bx-cat-name"></h4>' +
      '<p class="bx-cat-desc"></p>';

    card.querySelector('.bx-cat-name').textContent = data.name;
    card.querySelector('.bx-cat-desc').textContent = data.description;
    grid.appendChild(card);
  },

  updateCategoryCard(data) {
    const card = document.querySelector('.bx-cat-card[data-category-id="' + data.id + '"]');
    if (!card) return;
    card.setAttribute('data-name', data.name);
    card.setAttribute('data-description', data.description);
    if (data.thumbnail_url) {
      card.setAttribute('data-thumbnail-url', data.thumbnail_url);
      let bg = card.querySelector('.bx-cat-bg');
      if (!bg) {
        bg = document.createElement('img');
        bg.className = 'bx-cat-bg';
        bg.alt = '';
        card.insertBefore(bg, card.firstChild);
      }
      bg.src = data.thumbnail_url;
    }
    card.querySelector('.bx-cat-name').textContent = data.name;
    card.querySelector('.bx-cat-desc').textContent = data.description;
  },

  addChipsEverywhere(data) {
    document.querySelectorAll('.category-chips-container').forEach(container => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'bx-chip';
      btn.setAttribute('data-value', data.id);
      btn.textContent = data.name;
      container.appendChild(btn);
    });
  },

  syncProjectTemplate(data, mode) {
    const tpl = document.getElementById('projects-empty-form');
    if (!tpl) return;
    const holder = document.createElement('div');
    holder.innerHTML = tpl.innerHTML;
    if (mode === 'add') {
      holder.querySelectorAll('.category-chips-container').forEach(container => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'bx-chip';
        btn.setAttribute('data-value', data.id);
        btn.textContent = data.name;
        container.appendChild(btn);
      });
    } else {
      holder.querySelectorAll('.bx-chip[data-value="' + data.id + '"], .category-chip[data-value="' + data.id + '"]').forEach(chip => {
        chip.textContent = data.name;
      });
    }
    tpl.innerHTML = holder.innerHTML;
  },

  deleteCategory(catId) {
    if (!confirm(bxt('confirmDeleteCollection'))) return;

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content;
    const deleteUrl = document.getElementById('ajax-delete-category-url')?.value;

    if (!csrfToken || !deleteUrl) {
      this.toast(bxt('msgTokenMissing'), 'error');
      return;
    }

    const formData = new FormData();
    formData.append('id', catId);

    fetch(deleteUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken },
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          this.toast(data.error || bxt('msgDeleteCategoryFail'), 'error');
          return;
        }

        const card = document.querySelector('.bx-cat-card[data-category-id="' + catId + '"]');
        if (card) card.remove();

        const grid = document.getElementById('builder-categories-grid');
        if (grid && !grid.querySelector('.bx-cat-card')) {
          const empty = document.createElement('div');
          empty.id = 'no-categories-state';
          empty.style.gridColumn = '1/-1';
          empty.className = 'bx-empty';
          empty.innerHTML = '<p class="bx-empty-title" style="margin:0;">' + bxt('emptyCollectionsTitle') + '</p><p class="bx-empty-sub" style="margin:0 0 4px;">' + bxt('emptyCollectionsSub') + '</p>';
          grid.appendChild(empty);
        }

        document.querySelectorAll('.category-chips-container').forEach(container => {
          const chip = container.querySelector('[data-value="' + catId + '"]');
          if (chip) {
            if (chip.classList.contains('is-active') || chip.classList.contains('active')) {
              const uncategorized = container.querySelector('[data-value=""]');
              if (uncategorized) uncategorized.click();
            }
            chip.remove();
          }
        });

        const tpl = document.getElementById('projects-empty-form');
        if (tpl) {
          const holder = document.createElement('div');
          holder.innerHTML = tpl.innerHTML;
          holder.querySelectorAll('[data-value="' + catId + '"]').forEach(c => c.remove());
          tpl.innerHTML = holder.innerHTML;
        }

        this.toast(bxt('msgCategoryDeleted'), 'success');
      })
      .catch(() => {
        this.toast(bxt('msgServerError'), 'error');
      });
  },

  toggleReview(reviewId, btn) {
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content;
    if (!csrfToken) {
      this.toast(bxt('msgTokenMissing'), 'error');
      return;
    }

    const formData = new FormData();
    formData.append('next', window.location.pathname + window.location.search);

    fetch('/dashboard/reviews/' + reviewId + '/toggle/', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken },
      body: formData
    })
      .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const card = document.querySelector('.bx-review-card[data-review-id="' + reviewId + '"]');
        if (!card) return;

        const featured = card.dataset.featured === '1';
        const listed = !featured;
        card.dataset.featured = listed ? '1' : '0';

        const badge = card.querySelector('.bx-badge');
        if (badge) {
          badge.textContent = listed ? (badge.dataset.listedLabel || bxt('badgeListed')) : (badge.dataset.pendingLabel || bxt('badgePending'));
          badge.classList.toggle('is-listed', listed);
          badge.classList.toggle('is-pending', !listed);
        }

        btn.textContent = listed ? (btn.dataset.removeLabel || bxt('btnRemoveFromPortfolio')) : (btn.dataset.listLabel || bxt('btnListOnPortfolio'));
        btn.classList.toggle('is-on', listed);
        btn.classList.toggle('is-off', !listed);

        this.toast(listed ? bxt('msgReviewLive') : bxt('msgReviewHidden'), 'success');
        this.updateNavStates();
      })
      .catch(() => {
        this.toast(bxt('msgNetworkError'), 'error');
      });
  },

  toast(message, type, action) {
    const host = document.getElementById(type === 'error' ? 'bx-toasts-alert' : 'bx-toasts');
    if (!host) return;

    const toast = document.createElement('div');
    toast.className = 'bx-toast is-' + (type || 'info');
    toast.setAttribute('role', 'status');

    const dot = document.createElement('span');
    dot.className = 'bx-toast-dot';
    toast.appendChild(dot);

    const text = document.createElement('span');
    text.textContent = message;
    toast.appendChild(text);

    if (action) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'bx-toast-action';
      btn.textContent = action.label;
      btn.addEventListener('click', () => {
        action.fn();
        dismiss();
      });
      toast.appendChild(btn);
    }

    host.appendChild(toast);

    let dismissed = false;
    const dismiss = () => {
      if (dismissed) return;
      dismissed = true;
      toast.classList.add('is-leaving');
      setTimeout(() => toast.remove(), 240);
    };

    setTimeout(dismiss, action ? 6000 : (type === 'error' ? 4500 : 3000));
  },

  openFromHash() {
    if (!location.hash) return;
    const key = location.hash.slice(1);
    if (this.order.includes(key)) this.goTo(key);
  }
};

document.addEventListener('DOMContentLoaded', () => BX.init());
