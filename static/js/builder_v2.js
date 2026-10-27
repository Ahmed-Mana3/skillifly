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
  clientReadyOf: 'Client-ready {done}/3',
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
  msgReviewHidden: 'Review hidden from your portfolio.',
  secOrder: 'Section layout',
  msgOrderSaved: 'Layout saved — your portfolio now shows sections in this order.',
  msgOrderSaveFail: 'Failed to save the layout — please try again.',
  msgOrderReset: 'Section order reset to the theme default.',
  msgOrderResetFail: 'Failed to reset — please try again.',
  msgOrderMinVisible: 'At least one section must stay visible.',
  orderHideSection: 'Hide',
  orderShowSection: 'Show',
  orderMoveUp: 'Move up',
  orderMoveDown: 'Move down',
  orderSaving: ' Saving…',
  orderStatusUnsaved: 'Unsaved changes',
  orderConfirmResetTitle: 'Reset section layout?',
  orderConfirmResetDesc: 'This clears your custom order and shows every section again. You can re-arrange afterwards, but this step can\u2019t be undone.',
  orderConfirmResetOk: 'Reset layout',
  msgOrderAlreadyDefault: 'Already using the theme default order.',
  msgOrderFlushFail: 'Your section layout couldn\u2019t be saved, so nothing else was saved either. Please try again.',
  orderLiveMoved: '{name} moved to position {n} of {total}',
  orderLiveHidden: '{name} hidden from your portfolio',
  orderLiveShown: '{name} visible again',
  orderLiveSaved: 'Layout saved.',
  autosaveSaved: 'All changes saved',
  autosaveSaving: 'Saving…',
  autosaveError: 'Some changes didn’t save',
  autosaveSignedOut: 'You were signed out. Sign in again to save your changes.',
  autosaveDraft: 'Fill in the required fields to save the new item',
  autosaveFirstVideo: 'Your first video is on your portfolio.',
  autosaveSeeIt: 'See it',
  moreSections: 'More sections ({n})',
  fewerSections: 'Fewer sections',
  detailsEdit: 'Edit',
  detailsClose: 'Close',
  linkLookingUp: 'Looking up the video…',
  linkDuplicate: 'This video is already in your portfolio.',
  pasteEmpty: 'Paste a video link first.',
  orderSaveFail: 'Couldn’t save the new order. Try again.',
  linkCopied: 'Link copied. Paste it to your client.',
  copyFallback: 'Copy your portfolio link:',
  skillsMax: 'You can show up to {n} skills.',
  linkLabel: 'Link'
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
  layoutFlushed: false,
  undoStack: [],
  lastSubmitter: null,
  order: ['identity', 'skills', 'education', 'experience', 'projects', 'links', 'creators', 'reviews', 'order'],

  ORDERS_BY_CATEGORY: {
    student: ['identity', 'education', 'skills', 'experience', 'projects', 'creators', 'reviews', 'links', 'order'],
    // Video editors: what clients look at first. The work, who made it, tools, where to follow, proof.
    video_editor: ['projects', 'identity', 'skills', 'links', 'reviews', 'experience', 'education', 'creators', 'order'],
    developer: ['identity', 'skills', 'experience', 'projects', 'creators', 'reviews', 'education', 'links', 'order']
  },

  // Optional sections folded under "More sections" in the sidebar until they have content.
  EXTRAS_BY_CATEGORY: {
    video_editor: ['experience', 'education', 'creators', 'order']
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
    BXAutosave.init(this.root);
    BXSectionOrder.init();
    BXVideos.init(this.root);
    BXSkills.init();
    BXLinks.init();
    this.setupCharCounters();
    this.refreshEmptyStates();
    this.updateNavStates();
    this.foldExtraSections();
    this.addDoneButtons();
    this.openFromHash();
  },

  // Video editors: optional sections that are still empty wait under "More sections".
  foldExtraSections() {
    const extras = (this.EXTRAS_BY_CATEGORY[this.category] || []).filter(key => this.navByKey[key]);
    const folded = extras.filter(key => !this.isSectionDone(key));
    if (!folded.length) return;
    const firstLi = this.navByKey[extras[0]].closest('li');
    const li = document.createElement('li');
    li.className = 'bx-nav-more-li';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'bx-nav-more';
    btn.dataset.action = 'toggle-more';
    btn.setAttribute('aria-expanded', 'false');
    btn.textContent = bxt('moreSections', { n: folded.length });
    li.appendChild(btn);
    this.navList.insertBefore(li, firstLi);
    this.foldedKeys = folded;
    this.moreBtn = btn;
    folded.forEach(key => this.navByKey[key].closest('li').classList.add('is-folded'));
  },

  toggleMore(open) {
    if (!this.moreBtn) return;
    const expand = open === undefined ? this.moreBtn.getAttribute('aria-expanded') !== 'true' : open;
    this.moreBtn.setAttribute('aria-expanded', expand ? 'true' : 'false');
    this.moreBtn.textContent = expand ? bxt('fewerSections') : bxt('moreSections', { n: this.foldedKeys.length });
    this.foldedKeys.forEach(key => this.navByKey[key].closest('li').classList.toggle('is-folded', !expand));
  },

  // Autosave has no Save button, so the last sections end with a way out.
  addDoneButtons() {
    const tpl = document.getElementById('bx-done-tpl');
    if (!BXAutosave.on || !tpl) return;
    const extras = this.EXTRAS_BY_CATEGORY[this.category] || [];
    const primary = this.order.filter(key => extras.indexOf(key) === -1);
    const keys = [primary[primary.length - 1], this.order[this.order.length - 1]];
    keys.filter((key, i) => key && keys.indexOf(key) === i).forEach(key => {
      const end = this.panelByKey[key] && this.panelByKey[key].querySelector('.bx-foot-end');
      if (end) end.appendChild(tpl.content.cloneNode(true));
    });
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
    // Preferred keys whose panel is absent (e.g. the layout panel only ships
    // for the minimal theme) are dropped; reordering only requires that the
    // remaining keys cover every rendered panel.
    const valid = preferred.filter(k => this.panelByKeyExists(k));
    if (valid.length !== this.panels.length) return;

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
        const ready = e.target.closest('.bx-ready-item');
        if (ready) this.openReadyItem(ready);
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
        case 'order-up': BXSectionOrder.moveRow(actionEl.closest('.bx-order-row'), -1); break;
        case 'order-down': BXSectionOrder.moveRow(actionEl.closest('.bx-order-row'), 1); break;
        case 'order-toggle-visibility': BXSectionOrder.toggleVisibility(actionEl.closest('.bx-order-row')); break;
        case 'order-preset': BXSectionOrder.applyPreset(actionEl.dataset.order); break;
        case 'order-save': BXSectionOrder.save(); break;
        case 'order-reset': BXSectionOrder.reset(); break;
        case 'order-confirm-save': BXSectionOrder.confirmReset(); break;
        case 'order-confirm-cancel': BXSectionOrder.closeConfirm(); break;
        case 'autosave-retry': BXAutosave.retryAll(); break;
        case 'toggle-more': this.toggleMore(); break;
        case 'copy-link': this.copyPortfolioLink(); break;
        case 'keep-title': this.keepTitle(); break;
        case 'paste-add': BXVideos.addFromPaste(); break;
        case 'toggle-details': BXVideos.toggleDetails(actionEl.closest('.bx-item')); break;
        case 'move-up': BXVideos.move(actionEl.closest('.bx-item'), -1, actionEl); break;
        case 'move-down': BXVideos.move(actionEl.closest('.bx-item'), 1, actionEl); break;
        case 'toggle-skill': BXSkills.toggle(actionEl); break;
        case 'add-skill': BXSkills.addFromInput(); break;
      }
    });

    document.addEventListener('click', (e) => {
      const saver = e.target.closest('[data-save-button]');
      if (saver && this.form.contains(saver) || saver && saver.getAttribute('form') === 'portfolio-form') {
        this.lastSubmitter = saver;
      }
    });

    // Helper inputs without a name (paste a link, add a skill) are not portfolio data.
    this.form.addEventListener('input', (e) => {
      if (!e.target.name) return;
      if (e.target.name === 'title') this.confirmTitle();
      this.markDirty();
      this.scheduleProgress();
      BXVideos.onInput(e.target);
      BXLinks.onInput(e.target);
      BXAutosave.onFieldEvent(e.target, false);
    });
    this.form.addEventListener('change', (e) => {
      if (!e.target.name) return;
      this.markDirty();
      this.scheduleProgress();
      if (e.target.matches('input[type="file"]')) this.handleFileChange(e.target);
      BXVideos.onInput(e.target);
      BXAutosave.onFieldEvent(e.target, true);
    });
    // Enter in a helper input adds what it holds instead of posting the form.
    this.form.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      if (e.target.id === 'bx-paste-input') { e.preventDefault(); BXVideos.addFromPaste(); }
      if (e.target.id === 'bx-skill-new') { e.preventDefault(); BXSkills.addFromInput(); }
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
      const layoutPending = !!(BXSectionOrder.list && BXSectionOrder.hasPending());
      const unsaved = BXAutosave.on ? BXAutosave.hasUnsaved() : (this.isDirty || layoutPending);
      if (unsaved && !this.isSubmitting) {
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

  // `silent` switches panels without touching the URL hash, scroll position or focus.
  // Used for the initial panel on page load, which must not move the page.
  goTo(key, { silent = false } = {}) {
    const panel = this.panelByKey[key];
    if (!panel || key === this.currentKey) return;
    if (this.foldedKeys && this.foldedKeys.indexOf(key) !== -1) this.toggleMore(true);

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
    if (silent) return;
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

  async handleSubmit(e) {
    if (this.isSubmitting) {
      e.preventDefault();
      return;
    }
    // Autosave: Enter in a field must not post the whole form; save what is waiting instead.
    if (BXAutosave.on) {
      e.preventDefault();
      BXAutosave.saveAll();
      return;
    }

    // The section layout saves through its own AJAX endpoint, so the form POST
    // would silently drop pending layout edits. Flush them first, then replay
    // the submit. preventDefault must run synchronously — before any await —
    // or the browser navigates away mid-flush.
    if (this.layoutFlushed) {
      this.layoutFlushed = false;
    } else if (BXSectionOrder.list && BXSectionOrder.hasPending()) {
      e.preventDefault();
      const flushed = await BXSectionOrder.flush();
      if (!flushed) {
        this.toast(bxt('msgOrderFlushFail'), 'error');
        this.goTo('order');
        return;
      }
      this.layoutFlushed = true;
      try {
        this.form.requestSubmit(e.submitter || undefined);
      } catch (err) {
        this.form.requestSubmit();
      }
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

  // Keep the progress bar and the sidebar ticks live while the user types.
  // Batched to one update per animation frame so fast typing stays cheap.
  scheduleProgress() {
    if (this._progressFrame) return;
    const run = () => { this._progressFrame = 0; this.updateNavStates(); };
    this._progressFrame = window.requestAnimationFrame ? window.requestAnimationFrame(run) : setTimeout(run, 16);
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

  // Returns the new row. `focus: false` leaves the caret where it is (the row is filled by script).
  addItem(prefix, { focus = true } = {}) {
    const template = document.getElementById(prefix + '-empty-form');
    const container = document.getElementById(prefix + '-container');
    const totalForms = document.getElementById('id_' + prefix + '-TOTAL_FORMS');
    if (!template || !container || !totalForms) return null;

    const count = parseInt(totalForms.value, 10);
    const wrapper = document.createElement('div');
    wrapper.className = prefix === 'projects' ? 'bx-item bx-video' : 'bx-item';
    wrapper.innerHTML = template.innerHTML.replace(/__prefix__/g, count);

    container.prepend(wrapper);
    totalForms.value = count + 1;
    if (prefix === 'projects') BXVideos.setupCard(wrapper, { expanded: focus });

    this.refreshEmptyStates();
    this.markDirty();
    this.updateNavStates();

    const firstInput = wrapper.querySelector('input:not([type=hidden]):not([type=file]), textarea');
    if (firstInput && focus) {
      firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => firstInput.focus({ preventScroll: true }), 300);
    }
    return wrapper;
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
    BXAutosave.onRemove(item);
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
    BXAutosave.onRestore(entry.item);
    this.afterRemoval();
    this.toast(bxt('msgRestored'), 'success');
  },

  afterRemoval() {
    this.refreshEmptyStates();
    this.updateNavStates();
    this.markDirty();
    BXSkills.refresh();
    BXVideos.scheduleOrder();
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
        // A video counts with a link alone (its title comes from the link); so does a link.
        const coreFields = {
          skills: '[name$="-skill"]',
          education: '[name$="-school"]',
          experience: '[name$="-title"]',
          projects: '[name$="-name"], [name$="-url"]',
          links: '[name$="-url"]',
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

  // The three things that make a video editor's portfolio worth sending to a client.
  // Mirrors core.onboarding.client_ready on the server.
  PLACEHOLDER_TITLES: ['video editor', 'مونتير فيديو'],

  clientReadyItems() {
    const value = name => {
      const el = this.form && this.form.querySelector('[name="' + name + '"]');
      return el ? el.value.trim() : '';
    };
    const container = document.getElementById('projects-container');
    // One per video row that has a title or a link and isn't removed.
    const videos = container
      ? Array.from(container.querySelectorAll('[name$="-name"]')).filter(inp => {
          const item = inp.closest('.bx-item');
          const link = item && item.querySelector ? item.querySelector('[name$="-url"]') : null;
          if (!inp.value.trim() && !(link && link.value.trim())) return false;
          return !(item && (item.classList.contains('is-removed') || item.style.display === 'none'));
        }).length
      : 0;
    const title = value('title');
    return {
      videoCount: videos,
      videos: videos >= 3,
      // The signup default counts once the user keeps it (core.onboarding.title_counts).
      title: !!title && (!this.isPlaceholderTitle(title) || value('title_confirmed') === '1'),
      contact: !!(value('booking_url') || value('phone'))
    };
  },

  isPlaceholderTitle(title) {
    return this.PLACEHOLDER_TITLES.indexOf((title || '').trim().toLowerCase()) !== -1;
  },

  // Typing in the title, or pressing "Keep this title", makes it the user's own.
  confirmTitle() {
    const flag = document.getElementById('f-title-confirmed');
    if (flag) flag.value = '1';
  },

  keepTitle() {
    this.confirmTitle();
    const title = document.getElementById('f-title');
    if (title) title.dispatchEvent(new Event('input', { bubbles: true })); // autosave sends it: confirmed
    this.paintTitleKeep();
  },

  paintTitleKeep() {
    const prompt = document.querySelector('[data-title-keep]');
    const title = document.getElementById('f-title');
    const flag = document.getElementById('f-title-confirmed');
    if (!prompt || !title || !flag) return;
    prompt.hidden = !(this.isPlaceholderTitle(title.value) && flag.value !== '1');
  },

  clientReadyCount() {
    const items = this.clientReadyItems();
    return [items.videos, items.title, items.contact].filter(Boolean).length;
  },

  refreshProgress() {
    this.paintTitleKeep();
    const fill = document.getElementById('bx-progress-fill');
    const label = document.getElementById('bx-progress-label');
    if (!fill || !label) return;
    if (this.category === 'video_editor') {
      const items = this.clientReadyItems();
      const ready = [items.videos, items.title, items.contact].filter(Boolean).length;
      fill.style.width = Math.round((ready / 3) * 100) + '%';
      label.textContent = bxt('clientReadyOf', { done: ready });
      this.paintReadiness(items, ready);
      return;
    }
    const done = this.ACTIONABLE_SECTIONS.filter(k => this.isSectionDone(k)).length;
    const total = this.ACTIONABLE_SECTIONS.length;
    const pct = Math.round((done / total) * 100);
    fill.style.width = pct + '%';
    label.textContent = bxt('progressOf', { done: done, total: total });
  },

  // The sidebar's readiness block: tick what's done; once all three are, fold into one line.
  paintReadiness(items, ready) {
    const card = document.getElementById('bx-ready');
    if (!card) return;
    ['videos', 'title', 'contact'].forEach(key => {
      const el = card.querySelector('[data-ready="' + key + '"]');
      if (el) el.classList.toggle('is-done', !!items[key]);
    });
    const count = card.querySelector('[data-ready-count]');
    if (count) count.textContent = items.videos ? '' : Math.min(items.videoCount, 3) + '/3';
    const done = ready === 3;
    card.classList.toggle('is-ready', done);
    const todo = card.querySelector('[data-ready-todo]');
    const doneLine = card.querySelector('[data-ready-done]');
    if (todo) todo.hidden = done;
    if (doneLine) doneLine.hidden = !done;
  },

  openReadyItem(item) {
    const key = item.dataset.goto;
    if (key) this.goTo(key);
    const target = item.dataset.focus ? document.querySelector(item.dataset.focus)
      : (key === 'projects' ? document.getElementById('bx-paste-input') : null);
    if (target) setTimeout(() => target.focus({ preventScroll: false }), 350);
  },

  copyPortfolioLink() {
    const url = this.root ? this.root.dataset.portfolioUrl : '';
    if (!url) return;
    const done = () => this.toast(bxt('linkCopied'), 'success');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, () => window.prompt(bxt('copyFallback'), url));
    } else {
      window.prompt(bxt('copyFallback'), url);
    }
  },

  selectChip(chip) {
    const container = chip.closest('.category-chips-container');
    if (!container) return;
    container.querySelectorAll('.bx-chip').forEach(c => c.classList.remove('is-active'));
    chip.classList.add('is-active');
    const hidden = chip.closest('.bx-item').querySelector('.project-category-input');
    if (hidden) {
      hidden.value = chip.dataset.value;
      // A script-set value fires no event; this one lets autosave pick the chip up.
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
    }
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
    if (location.hash) {
      const key = location.hash.slice(1);
      if (this.order.includes(key)) this.goTo(key);
      return;
    }
    // No deep link: open the first section of this category's order (Work showcase
    // for video editors) rather than always "identity".
    const first = this.order[0];
    if (first && first !== this.currentKey) this.goTo(first, { silent: true });
  }
};

/* ========================================================================
   Video cards (Work panel). Each row shows as a card (thumbnail, title, format,
   link host) with its fields folded underneath. Pasting a link looks it up
   (welcome_preview_link) and fills in the title, format and thumbnail. Cards move
   with the arrows or by dragging the handle; the order saves on its own.
   ======================================================================== */
const BXVideos = {
  LOOKUP_DEBOUNCE_MS: 600,
  ORDER_DEBOUNCE_MS: 500,

  init(root) {
    this.container = document.getElementById('projects-container');
    if (!root || !this.container) return;
    this.previewUrl = root.dataset.linkPreviewUrl || '';
    this.orderUrl = root.dataset.orderUrl || '';
    this.lang = root.dataset.lang === 'ar' ? 'ar' : 'en';
    this.paste = document.getElementById('bx-paste-input');
    this.rows().forEach(row => this.setupCard(row, { expanded: false }));
    this.savedOrder = this.orderIds().join(',');
    this.bindDrag();
  },

  rows() {
    return this.container ? Array.from(this.container.querySelectorAll(':scope > .bx-item')) : [];
  },

  field(row, suffix) {
    return row.querySelector('[name$="-' + suffix + '"]');
  },

  // Fill the card header from the fields. A row with something in it starts folded,
  // unless a field shows an error (from the server or the browser).
  setupCard(row, { expanded = false } = {}) {
    if (!row || !row.querySelector('.bx-vcard')) return;
    this.syncCard(row);
    const hasContent = !!((this.field(row, 'name') || {}).value || (this.field(row, 'url') || {}).value);
    const hasError = Array.from(row.querySelectorAll('.bx-field-error')).some(el => el.textContent.trim());
    this.setExpanded(row, expanded || !hasContent || hasError);
  },

  setExpanded(row, open) {
    row.classList.toggle('is-collapsed', !open);
    const btn = row.querySelector('[data-action="toggle-details"]');
    if (btn) {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.textContent = open ? bxt('detailsClose') : bxt('detailsEdit');
    }
  },

  toggleDetails(row) {
    if (row) this.setExpanded(row, row.classList.contains('is-collapsed'));
  },

  syncCard(row) {
    const name = this.field(row, 'name');
    const url = this.field(row, 'url');
    const type = this.field(row, 'video_type');
    const title = row.querySelector('[data-vcard-title]');
    if (title) {
      const text = name && name.value.trim();
      title.textContent = text || title.dataset.empty || '';
      title.classList.toggle('is-placeholder', !text);
    }
    const host = row.querySelector('[data-vcard-host]');
    if (host) host.textContent = this.hostOf(url ? url.value : '');
    const badge = row.querySelector('[data-vcard-format]');
    if (badge && type) {
      const option = type.options ? type.options[type.selectedIndex] : null;
      badge.textContent = option ? option.text : '';
      badge.classList.toggle('is-reel', type.value === 'reel');
    }
    const img = row.querySelector('[data-vcard-img]');
    if (img && (!img.getAttribute('src') || img.dataset.auto === '1')) {
      const yt = this.youtubeThumb(url ? url.value : '');
      if (yt) {
        img.src = yt;
        img.hidden = false;
        img.dataset.auto = '1';
      }
    }
  },

  hostOf(url) {
    const raw = (url || '').trim();
    if (!raw) return '';
    try {
      return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : 'https://' + raw).hostname.replace(/^www\./, '');
    } catch (err) {
      return '';
    }
  },

  youtubeThumb(url) {
    const match = /(?:youtu\.be\/|youtube\.com\/(?:shorts\/|embed\/|v\/|.*[?&]v=))([\w-]{11})/.exec(url || '');
    return match ? 'https://i.ytimg.com/vi/' + match[1] + '/hqdefault.jpg' : '';
  },

  setThumb(row, src) {
    const img = row.querySelector('[data-vcard-img]');
    if (!img || !src) return;
    img.src = src;
    img.hidden = false;
    img.dataset.auto = '0';
  },

  setStatus(row, message, kind) {
    const el = row.querySelector('[data-link-status]');
    if (!el) return;
    el.textContent = message || '';
    el.hidden = !message;
    el.classList.toggle('is-error', kind === 'error');
    el.classList.toggle('is-warn', kind === 'warn');
  },

  // Called for every input/change in the form.
  onInput(field) {
    const row = field.closest && field.closest('.bx-video');
    if (!row) return;
    if (field.type === 'file') {
      const file = field.files && field.files[0];
      if (file && typeof FileReader === 'function') {
        const reader = new FileReader();
        reader.onload = ev => this.setThumb(row, ev.target.result);
        reader.readAsDataURL(file);
      }
      return;
    }
    this.syncCard(row);
    if (field.hasAttribute('data-video-link')) this.scheduleLookup(row);
  },

  scheduleLookup(row) {
    clearTimeout(row._lookupTimer);
    row._lookupTimer = setTimeout(() => this.lookup(row), this.LOOKUP_DEBOUNCE_MS);
  },

  async lookup(row) {
    const url = this.field(row, 'url');
    const value = url ? url.value.trim() : '';
    if (!value || !this.previewUrl || value === row._lookedUp) {
      if (!value) this.setStatus(row, '');
      return;
    }
    row._lookedUp = value;
    this.setStatus(row, bxt('linkLookingUp'));
    let data;
    try {
      const res = await fetch(this.previewUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': BXAutosave.csrf() },
        body: JSON.stringify({ url: value, lang: this.lang })
      });
      if (res.status === 429) { this.setStatus(row, ''); return; }
      data = await res.json();
    } catch (err) {
      this.setStatus(row, '');
      return;
    }
    if (url.value.trim() !== value) return; // the user kept typing; a newer lookup follows
    if (!data.ok) {
      this.setStatus(row, data.message || '', data.hard ? 'error' : 'warn');
      if (data.hard) this.setExpanded(row, true);
      return;
    }
    this.setStatus(row, data.duplicate ? bxt('linkDuplicate') : '', data.duplicate ? 'warn' : '');
    const name = this.field(row, 'name');
    if (name && !name.value.trim() && data.title) {
      name.value = data.title;
      name.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const type = this.field(row, 'video_type');
    if (type && data.video_type && type.value !== data.video_type) {
      type.value = data.video_type;
      type.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const img = row.querySelector('[data-vcard-img]');
    if (data.thumbnail_url && img && (!img.getAttribute('src') || img.dataset.auto === '1')) {
      img.src = data.thumbnail_url;
      img.hidden = false;
      img.dataset.auto = '1';
    }
    this.syncCard(row);
  },

  // "Paste a link" box: a new card at the top, filled in from the link.
  addFromPaste() {
    if (!this.paste) return;
    const value = this.paste.value.trim();
    const error = document.querySelector('[data-paste-error]');
    if (!value) {
      if (error) { error.textContent = bxt('pasteEmpty'); error.classList.add('is-visible'); }
      this.paste.focus();
      return;
    }
    if (error) { error.textContent = ''; error.classList.remove('is-visible'); }
    const row = BX.addItem('projects', { focus: false });
    if (!row) return;
    const url = this.field(row, 'url');
    url.value = value;
    url.dispatchEvent(new Event('input', { bubbles: true }));
    url.dispatchEvent(new Event('change', { bubbles: true }));
    this.setExpanded(row, false);
    this.lookup(row);
    this.paste.value = '';
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },

  // --- order ---------------------------------------------------------------

  move(row, delta, focusEl) {
    if (!row) return;
    const visible = this.rows().filter(r => !r.classList.contains('is-removed'));
    const index = visible.indexOf(row);
    const target = visible[index + delta];
    if (!target) return;
    if (delta < 0) this.container.insertBefore(row, target);
    else this.container.insertBefore(row, target.nextSibling);
    if (focusEl) focusEl.focus();
    this.scheduleOrder();
  },

  bindDrag() {
    let dragged = null;
    this.container.addEventListener('mousedown', e => {
      const handle = e.target.closest('[data-drag-handle]');
      const row = handle && handle.closest('.bx-item');
      if (row) row.draggable = true;
    });
    this.container.addEventListener('dragstart', e => {
      const row = e.target.closest && e.target.closest('.bx-item');
      if (!row || !row.draggable) return;
      dragged = row;
      row.classList.add('is-dragging');
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
      }
    });
    this.container.addEventListener('dragover', e => {
      if (!dragged) return;
      e.preventDefault();
      const over = e.target.closest && e.target.closest('.bx-item');
      if (!over || over === dragged) return;
      const box = over.getBoundingClientRect();
      const after = e.clientY > box.top + box.height / 2;
      this.container.insertBefore(dragged, after ? over.nextSibling : over);
    });
    const end = () => {
      if (!dragged) return;
      dragged.classList.remove('is-dragging');
      dragged.draggable = false;
      dragged = null;
      this.scheduleOrder();
    };
    this.container.addEventListener('drop', e => { if (dragged) e.preventDefault(); end(); });
    this.container.addEventListener('dragend', end);
  },

  scheduleOrder() {
    if (!this.container || !this.orderUrl) return;
    clearTimeout(this.orderTimer);
    BXAutosave.setExtra('order', 'pending');
    this.orderTimer = setTimeout(() => this.saveOrder(), this.ORDER_DEBOUNCE_MS);
  },

  orderIds() {
    return this.rows()
      .filter(row => !row.classList.contains('is-removed'))
      .map(row => parseInt((this.field(row, 'id') || {}).value, 10))
      .filter(id => id > 0);
  },

  async saveOrder() {
    const ids = this.orderIds();
    const key = ids.join(',');
    if (key === this.savedOrder) {
      BXAutosave.setExtra('order', 'saved');
      return;
    }
    const body = new FormData();
    ids.forEach(id => body.append('ids', id));
    BXAutosave.setExtra('order', 'saving');
    try {
      const res = await fetch(this.orderUrl, {
        method: 'POST', body, credentials: 'same-origin', headers: { 'X-CSRFToken': BXAutosave.csrf() }
      });
      if (!res.ok) throw new Error(String(res.status));
      this.savedOrder = key;
      BXAutosave.setExtra('order', 'saved');
    } catch (err) {
      BXAutosave.setExtra('order', 'error');
      if (!BXAutosave.on) BX.toast(bxt('orderSaveFail'), 'error');
    }
  }
};

/* ========================================================================
   Skill chips. Tap a preset (the launch checklist's list) or add your own.
   Every picked skill is a hidden .bx-item row in #skills-container, so saving
   (form POST or autosave) works as for any other row; a row a preset chip
   already shows is hidden.
   ======================================================================== */
const BXSkills = {
  MAX: 20,

  init() {
    this.container = document.getElementById('skills-container');
    this.input = document.getElementById('bx-skill-new');
    this.presets = Array.from(document.querySelectorAll('.bx-skill-preset'));
    this.refresh();
  },

  rows() {
    return this.container
      ? Array.from(this.container.querySelectorAll(':scope > .bx-item')).filter(r => !r.classList.contains('is-removed'))
      : [];
  },

  valueOf(row) {
    const input = row.querySelector('[data-skill-value]');
    return input ? input.value.trim() : '';
  },

  presetFor(value) {
    const key = value.trim().toLocaleLowerCase();
    return this.presets.find(btn => (btn.dataset.names || '').split('|').indexOf(key) !== -1) || null;
  },

  // Press the presets that are picked; hide their rows (the chip already shows them).
  refresh() {
    if (!this.container) return;
    const picked = new Set();
    this.rows().forEach(row => {
      const preset = this.presetFor(this.valueOf(row));
      row.classList.toggle('is-preset', !!preset);
      if (preset) picked.add(preset);
    });
    this.presets.forEach(btn => {
      const on = picked.has(btn);
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  },

  toggle(btn) {
    const row = this.rows().find(r => this.presetFor(this.valueOf(r)) === btn);
    if (row) {
      const remove = row.querySelector('[data-action="remove-item"]');
      if (remove) BX.removeItem(remove);
    } else {
      this.add(btn.dataset.skill);
    }
  },

  addFromInput() {
    if (!this.input) return;
    const value = this.input.value.replace(/\s+/g, ' ').trim();
    if (!value) return;
    if (this.add(value)) this.input.value = '';
    this.input.focus();
  },

  add(value) {
    const name = (value || '').trim().slice(0, 60);
    if (!name || !this.container) return false;
    const key = name.toLocaleLowerCase();
    if (this.rows().some(r => this.valueOf(r).toLocaleLowerCase() === key)) return true; // already there
    if (this.rows().length >= this.MAX) {
      BX.toast(bxt('skillsMax', { n: this.MAX }), 'info');
      return false;
    }
    const preset = this.presetFor(name);
    const row = BX.addItem('skills', { focus: false });
    if (!row) return false;
    const input = row.querySelector('[data-skill-value]');
    const label = row.querySelector('[data-skill-label]');
    input.value = preset ? preset.dataset.skill : name;
    if (label) label.textContent = input.value;
    this.container.appendChild(row); // keep the order they were picked in
    input.dispatchEvent(new Event('change', { bubbles: true }));
    this.refresh();
    return true;
  }
};

/* ========================================================================
   Links: paste the URL and the name shows itself ("Instagram"), until the user
   types their own. Mirrors builder.services.platform_from_url.
   ======================================================================== */
const BXLinks = {
  PLATFORMS: [
    ['instagram.com', 'Instagram'], ['youtube.com', 'YouTube'], ['youtu.be', 'YouTube'],
    ['tiktok.com', 'TikTok'], ['vimeo.com', 'Vimeo'], ['behance.net', 'Behance'],
    ['linkedin.com', 'LinkedIn'], ['facebook.com', 'Facebook'], ['fb.com', 'Facebook'],
    ['x.com', 'X'], ['twitter.com', 'X'], ['threads.net', 'Threads'], ['wa.me', 'WhatsApp'],
    ['whatsapp.com', 'WhatsApp'], ['t.me', 'Telegram'], ['dribbble.com', 'Dribbble'],
    ['artstation.com', 'ArtStation'], ['github.com', 'GitHub'], ['snapchat.com', 'Snapchat'],
    ['pinterest.com', 'Pinterest'], ['calendly.com', 'Calendly'], ['drive.google.com', 'Google Drive']
  ],

  init() {
    document.querySelectorAll('#links-container > .bx-item').forEach(row => this.paintBadge(row));
  },

  platformFromUrl(url) {
    const host = BXVideos.hostOf(url).toLowerCase();
    if (!host) return '';
    const hit = this.PLATFORMS.find(([domain]) => host === domain || host.endsWith('.' + domain));
    return hit ? hit[1] : host;
  },

  paintBadge(row) {
    const badge = row.querySelector('[data-link-platform]');
    const name = row.querySelector('[data-link-name]');
    const url = row.querySelector('[data-link-url]');
    if (!badge) return;
    badge.textContent = (name && name.value.trim()) || this.platformFromUrl(url ? url.value : '') || bxt('linkLabel');
  },

  onInput(field) {
    const row = field.closest && field.closest('#links-container > .bx-item');
    if (!row) return;
    const name = row.querySelector('[data-link-name]');
    if (field.hasAttribute('data-link-url') && name && (name.dataset.auto === '1' || !name.value.trim())) {
      const platform = this.platformFromUrl(field.value);
      if (name.value !== platform) {
        name.value = platform;
        name.dataset.auto = '1';
        this.filling = true;
        name.dispatchEvent(new Event('input', { bubbles: true }));
        this.filling = false;
      }
    } else if (field.hasAttribute('data-link-name') && !this.filling) {
      field.dataset.auto = field.value.trim() ? '0' : '1';
    }
    this.paintBadge(row);
  }
};

/* ========================================================================
   Autosave (SiteSettings.builder_autosave_enabled, see BUILDER_AUTOSAVE_PLAN.md).
   Each row (one skill, one video, ...) and the personal-info panel saves itself
   through the per-item API in builder/api.py: text 800 ms after typing stops,
   everything else at once. Requests for one row never overlap, a new row is
   created once its required fields are filled, a value the server refused is
   held back until the user changes it (so it never blocks the rest), and a
   removed row is deleted only after its Undo toast has gone. Without the switch
   (or without JS) the page keeps its full-form Save.
   ======================================================================== */
const BXAutosave = {
  DEBOUNCE_MS: 800,
  DELETE_DELAY_MS: 6000, // the Undo toast stays up 6 s
  RETRY_DELAYS_MS: [1000, 3000, 9000],
  KINDS: ['skills', 'education', 'experience', 'projects', 'links', 'creators'],
  PERSONAL_FIELDS: ['fullname', 'title', 'email', 'phone', 'booking_url', 'bio', 'picture'],
  // Worst first: the status pill shows the first state any row is in.
  STATE_ORDER: ['signed_out', 'error', 'invalid', 'saving', 'pending', 'draft'],
  on: false,
  rows: [],
  layout: { state: 'saved', timer: null },
  extras: {},

  init(root) {
    this.on = !!(root && root.dataset.autosave === '1' && root.dataset.apiBase &&
                 typeof fetch === 'function' && typeof FormData === 'function');
    if (!this.on) return;
    this.base = root.dataset.apiBase;
    this.lang = root.dataset.lang === 'ar' ? 'ar' : 'en';
    this.fetch = (url, opts) => fetch(url, opts);
    this.statusEl = document.getElementById('bx-autosave-status');
    if (this.statusEl) this.statusEl.hidden = false;
    document.body.classList.add('bx-autosave-on');
    window.addEventListener('pagehide', () => this.flushOnExit());
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') this.saveAll();
    });
    this.refreshStatus();
  },

  // --- rows -----------------------------------------------------------------

  stateFor(el, kind) {
    let row = this.rows.find(r => r.el === el);
    if (!row) {
      row = {
        el, kind, id: this.readId(el, kind),
        dirty: new Set(), files: new Map(), rejected: {},
        state: 'saved', timer: null, retryTimer: null, attempts: 0, chain: Promise.resolve(),
        removed: false, deleteTimer: null, deleteSent: false
      };
      this.rows.push(row);
    }
    return row;
  },

  rowFor(el) {
    if (!el || !el.closest) return null;
    const panel = el.closest('#panel-identity');
    if (panel) return this.stateFor(panel, 'personal');
    const item = el.classList && el.classList.contains('bx-item') ? el : el.closest('.bx-item');
    const container = item && item.parentElement;
    const match = container && /^(\w+)-container$/.exec(container.id || '');
    if (!match || this.KINDS.indexOf(match[1]) === -1) return null;
    return this.stateFor(item, match[1]);
  },

  readId(el, kind) {
    if (kind === 'personal') return null;
    const input = el.querySelector('input[name$="-id"]');
    const id = input ? parseInt(input.value, 10) : NaN;
    return id > 0 ? id : null;
  },

  writeId(row) {
    const input = row.el.querySelector('input[name$="-id"]');
    if (input) input.value = row.id ? String(row.id) : '';
  },

  // The API's name for a builder input ("projects-3-name" -> "name"), or null.
  fieldName(row, field) {
    const name = field.name || '';
    if (row.kind === 'personal') return this.PERSONAL_FIELDS.indexOf(name) !== -1 ? name : null;
    const match = /^[a-z_]+-\d+-(\w+)$/.exec(name);
    return match && match[1] !== 'id' && match[1] !== 'DELETE' ? match[1] : null;
  },

  fields(row) {
    const out = {};
    row.el.querySelectorAll('input, textarea, select').forEach(field => {
      const name = this.fieldName(row, field);
      if (name) out[name] = field;
    });
    return out;
  },

  isValid(field) {
    return typeof field.checkValidity !== 'function' || field.checkValidity();
  },

  readyToCreate(fields, kind) {
    // A video needs its link or a title (the server fills the title in from the link).
    if (kind === 'projects') {
      const has = name => !!(fields[name] && fields[name].value.trim());
      if (!has('url') && !has('name')) return false;
    }
    return Object.keys(fields).every(name => {
      const field = fields[name];
      if (field.type === 'file') return true;
      if (field.required && !(field.value || '').trim()) return false;
      return this.isValid(field);
    });
  },

  // --- queueing -------------------------------------------------------------

  // Typing waits for a pause; selects, chips, dates and files save at once.
  onFieldEvent(field, immediate) {
    if (!this.on) return;
    const row = this.rowFor(field);
    if (!row || row.removed) return;
    const name = this.fieldName(row, field);
    if (!name) return;
    if (field.type === 'file') {
      // Some browsers fire "input" as well as "change" for a chosen file: upload it once.
      const file = field.files && field.files[0];
      if (!immediate || !file) return;
      row.files.set(name, file);
    } else {
      row.dirty.add(name);
    }
    this.schedule(row, immediate);
  },

  schedule(row, immediate) {
    clearTimeout(row.timer);
    clearTimeout(row.retryTimer);
    row.retryTimer = null;
    row.state = 'pending';
    row.timer = setTimeout(() => this.save(row), immediate ? 0 : this.DEBOUNCE_MS);
    this.refreshStatus();
  },

  // Requests for one row run one after another, so a create is never sent twice.
  save(row, opts) {
    clearTimeout(row.timer);
    row.timer = null;
    row.chain = row.chain.then(() => this.send(row, opts || {})).catch(() => {});
    return row.chain;
  },

  saveAll() {
    this.rows.forEach(row => { if (row.timer) this.save(row); });
    if (this.layout.timer) this.saveLayout();
  },

  retryAll() {
    this.rows.forEach(row => {
      if (row.removed || (row.state !== 'error' && row.state !== 'signed_out')) return;
      row.attempts = 0;
      this.save(row);
    });
    if (this.layout.state === 'error') this.saveLayout();
    if (this.extras.order === 'error') BXVideos.saveOrder();
  },

  urlFor(row, creating) {
    if (row.kind === 'personal') return this.base + 'personal/';
    return this.base + row.kind + '/' + (creating ? '' : row.id + '/');
  },

  csrf() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  },

  async send(row, opts) {
    if (row.removed) return;
    const creating = row.kind !== 'personal' && !row.id;
    const fields = this.fields(row);
    if (!row.dirty.size && !row.files.size) {
      this.settle(row);
      return;
    }
    if (creating && !this.readyToCreate(fields, row.kind)) {
      row.state = 'draft';
      this.refreshStatus();
      return;
    }

    // A create sends the whole row; an update only what changed. Values the browser
    // or the server already refused wait until the user changes them.
    const names = creating
      ? Object.keys(fields).filter(name => fields[name].type !== 'file')
      : Array.from(row.dirty).filter(name => fields[name]);
    const refusedNow = name => row.rejected[name] && row.rejected[name].value === fields[name].value;
    const held = names.filter(name => !this.isValid(fields[name]) || refusedNow(name));
    held.forEach(name => this.showError(fields[name], refusedNow(name) ? row.rejected[name].message : ''));
    const sending = creating && held.length ? [] : names.filter(name => held.indexOf(name) === -1);
    if (!sending.length && !(row.files.size && !creating)) {
      row.state = held.length ? 'invalid' : 'saved';
      this.refreshStatus();
      return;
    }

    const files = new Map(row.files);
    sending.forEach(name => row.dirty.delete(name));
    row.files.clear();
    const body = new FormData();
    body.append('lang', this.lang);
    sending.forEach(name => body.append(name, fields[name].value));
    files.forEach((file, name) => body.append(name, file));

    row.state = 'saving';
    this.refreshStatus();
    let res;
    let data;
    try {
      res = await this.fetch(this.urlFor(row, creating), {
        method: 'POST', body, credentials: 'same-origin', keepalive: !!opts.keepalive,
        headers: { 'X-CSRFToken': this.csrf() }
      });
      data = await res.json().catch(() => ({}));
    } catch (err) {
      this.retryLater(row, sending, files);
      return;
    }

    if (res.status === 404 && row.id) {
      // Removed elsewhere (another tab) while the user was editing it: add it back.
      row.id = null;
      this.writeId(row);
      Object.keys(fields).forEach(name => { if (fields[name].type !== 'file') row.dirty.add(name); });
      files.forEach((file, name) => row.files.set(name, file));
      await this.send(row, opts);
      return;
    }
    if (res.status === 401 || res.status === 403) {
      this.restore(row, sending, files);
      row.state = 'signed_out';
      this.refreshStatus();
      return;
    }
    if (res.status === 400) {
      const errors = (data && data.errors) || {};
      const refused = Object.keys(errors);
      refused.forEach(name => {
        const field = fields[name];
        if (!field) return;
        this.showError(field, errors[name][0]);
        if (field.type !== 'file') row.rejected[name] = { value: field.value, message: errors[name][0] };
      });
      // Nothing was saved: send the rest again without the refused values.
      this.restore(row, sending, files, refused);
      const progress = refused.some(name => sending.indexOf(name) !== -1);
      const rest = sending.filter(name => refused.indexOf(name) === -1);
      if (progress && (rest.length || (row.files.size && !creating))) {
        await this.send(row, opts);
      } else {
        row.state = 'invalid';
        this.refreshStatus();
      }
      return;
    }
    if (!res.ok || !data || !data.ok) {
      this.retryLater(row, sending, files);
      return;
    }

    row.attempts = 0;
    sending.forEach(name => {
      delete row.rejected[name];
      this.clearError(fields[name]);
    });
    files.forEach((file, name) => this.clearError(fields[name]));
    if (creating && data.id) {
      row.id = data.id;
      this.writeId(row);
      if (row.kind === 'projects') BXVideos.scheduleOrder(); // keep it where the user put it
    }
    if (data.reveal_url) this.announceFirstVideo(data.reveal_url);
    this.settle(row);
  },

  // After a request: the row is saved unless the user typed meanwhile or a value is held back.
  settle(row) {
    if (row.timer) row.state = 'pending';
    else if (row.dirty.size) row.state = 'invalid';
    else row.state = 'saved';
    this.refreshStatus();
  },

  // Put back what a failed request carried, so the next save sends it again.
  restore(row, sending, files, dropFiles) {
    sending.forEach(name => row.dirty.add(name));
    files.forEach((file, name) => {
      if (!dropFiles || dropFiles.indexOf(name) === -1) row.files.set(name, file);
    });
  },

  retryLater(row, sending, files) {
    this.restore(row, sending, files);
    const delay = this.RETRY_DELAYS_MS[row.attempts];
    row.attempts += 1;
    if (delay === undefined) {
      row.state = 'error';
    } else {
      row.state = 'pending';
      row.retryTimer = setTimeout(() => { row.retryTimer = null; this.save(row); }, delay);
    }
    this.refreshStatus();
  },

  // --- removing -------------------------------------------------------------

  onRemove(item) {
    if (!this.on) return;
    const row = this.rowFor(item);
    if (!row) return;
    row.removed = true;
    clearTimeout(row.timer);
    clearTimeout(row.retryTimer);
    row.timer = row.retryTimer = null;
    row.deleteTimer = setTimeout(() => this.sendDelete(row), this.DELETE_DELAY_MS);
    this.refreshStatus();
  },

  onRestore(item) {
    if (!this.on) return;
    const row = this.rowFor(item);
    if (!row) return;
    clearTimeout(row.deleteTimer);
    row.deleteTimer = null;
    row.removed = false;
    if (row.deleteSent) {
      // Undo came after the delete went out: create the row again.
      row.deleteSent = false;
      row.id = null;
      this.writeId(row);
      const fields = this.fields(row);
      Object.keys(fields).forEach(name => { if (fields[name].type !== 'file') row.dirty.add(name); });
    }
    if (row.dirty.size || row.files.size) this.schedule(row, true);
    else this.refreshStatus();
  },

  sendDelete(row, keepalive) {
    row.deleteTimer = null;
    row.chain = row.chain.then(async () => {
      if (!row.removed || !row.id || row.deleteSent) return;
      row.deleteSent = true;
      const body = new FormData();
      body.append('lang', this.lang);
      try {
        await this.fetch(this.base + row.kind + '/' + row.id + '/delete/', {
          method: 'POST', body, credentials: 'same-origin', keepalive: !!keepalive,
          headers: { 'X-CSRFToken': this.csrf() }
        });
      } catch (err) {
        row.deleteSent = false; // still on the server; the next exit or removal tries again
      }
    }).catch(() => {});
    return row.chain;
  },

  // Leaving the page: send what is still waiting, with keepalive so it outlives the page.
  flushOnExit() {
    this.rows.forEach(row => {
      if (row.deleteTimer) {
        clearTimeout(row.deleteTimer);
        this.sendDelete(row, true);
      } else if (row.timer) {
        this.save(row, { keepalive: true });
      }
    });
  },

  // --- section layout ---------------------------------------------------------

  layoutChanged() {
    if (!this.on) return;
    clearTimeout(this.layout.timer);
    this.layout.timer = null;
    if (!BXSectionOrder.hasPending()) {
      if (this.layout.state === 'pending') this.layout.state = 'saved';
      this.refreshStatus();
      return;
    }
    this.layout.state = 'pending';
    this.layout.timer = setTimeout(() => this.saveLayout(), this.DEBOUNCE_MS);
    this.refreshStatus();
  },

  async saveLayout() {
    clearTimeout(this.layout.timer);
    this.layout.timer = null;
    this.layout.state = 'saving';
    this.refreshStatus();
    const ok = await BXSectionOrder.flush();
    this.layout.state = !ok ? 'error' : (BXSectionOrder.hasPending() ? 'pending' : 'saved');
    if (this.layout.state === 'pending') this.layoutChanged();
    this.refreshStatus();
  },

  // --- what the user sees -----------------------------------------------------

  // Saves that aren't rows (the video order) report here too.
  setExtra(name, state) {
    this.extras[name] = state;
    this.refreshStatus();
  },

  overallState() {
    const states = this.rows.filter(row => !row.removed).map(row => row.state)
      .concat(this.layout.state, Object.keys(this.extras).map(key => this.extras[key]));
    return this.STATE_ORDER.find(state => states.indexOf(state) !== -1) || 'saved';
  },

  hasUnsaved() {
    return this.on && this.overallState() !== 'saved';
  },

  refreshStatus() {
    const el = this.statusEl;
    if (!el) return;
    const state = this.overallState();
    const labels = {
      saved: 'autosaveSaved', saving: 'autosaveSaving', pending: 'autosaveSaving', draft: 'autosaveDraft',
      invalid: 'autosaveError', error: 'autosaveError', signed_out: 'autosaveSignedOut'
    };
    el.dataset.state = state;
    const text = el.querySelector('.bx-autosave-text');
    if (text) text.textContent = bxt(labels[state]);
    const retry = el.querySelector('.bx-autosave-retry');
    if (retry) retry.hidden = state !== 'error' && state !== 'signed_out';
  },

  showError(field, message) {
    const wrap = field && field.closest ? field.closest('.bx-field') : null;
    if (!wrap) return;
    if (!message) {
      BX.validateField(field);
      return;
    }
    const errEl = wrap.querySelector('.bx-field-error');
    wrap.classList.add('has-error');
    field.setAttribute('aria-invalid', 'true');
    if (errEl) {
      errEl.textContent = message;
      errEl.classList.add('is-visible');
    }
  },

  clearError(field) {
    const wrap = field && field.closest ? field.closest('.bx-field') : null;
    if (!wrap || !wrap.classList.contains('has-error') || !this.isValid(field)) return;
    wrap.classList.remove('has-error');
    field.removeAttribute('aria-invalid');
    const errEl = wrap.querySelector('.bx-field-error');
    if (errEl) {
      errEl.textContent = '';
      errEl.classList.remove('is-visible');
    }
  },

  announceFirstVideo(url) {
    BX.toast(bxt('autosaveFirstVideo'), 'success', {
      label: bxt('autosaveSeeIt'),
      fn: () => window.open(url, '_blank', 'noopener')
    });
  }
};

/* ========================================================================
   Section layout panel — drag & drop ordering + visibility for the
   minimal theme. Talks to the ajax_save_section_layout endpoint; the
   public template reorders sections via CSS `order` (see
   portfolios/common/section_layout_css.html). Pending edits mark the page
   dirty (savebar + beforeunload) and are flushed by the main form submit
   so "Save changes" never drops them.
   ======================================================================== */
const BXSectionOrder = {
  DRAG_KEY: 'text/plain',

  init() {
    this.list = document.getElementById('bx-order-list');
    if (!this.list) return;
    this.confirmEl = document.getElementById('bx-order-confirm');
    this.status = document.getElementById('bx-order-status');
    this.saveBtn = document.getElementById('bx-order-save');
    this.resetBtn = this.list.closest('.bx-panel') ?
      this.list.closest('.bx-panel').querySelector('[data-action="order-reset"]') : null;
    this.liveEl = document.getElementById('bx-order-live');
    this.chips = Array.from(this.list.closest('.bx-panel')
      .querySelectorAll('[data-action="order-preset"]'));
    this.saveUrl = (document.getElementById('ajax-save-layout-url') || {}).value || '';
    this.saving = false;
    this.lastSavePromise = null;
    // Whether the SERVER currently holds a custom layout — drives the status
    // chip and lets "Reset" no-op when there is nothing saved to reset.
    this.serverCustom = !!(this.status && this.status.classList.contains('is-custom'));
    this.bindDrag();
    this.bindConfirm();
    this.baseline = this.serialize();
    this.refresh();
  },

  bindConfirm() {
    if (!this.confirmEl) return;

    this.confirmEl.addEventListener('click', (e) => {
      if (e.target === this.confirmEl) this.closeConfirm();
    });

    this.confirmEl.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        this.closeConfirm();
        return;
      }
      if (e.key !== 'Tab') return;
      const els = Array.from(this.confirmEl.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )).filter(el => !el.disabled && el.offsetParent !== null);
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
    });
  },

  rows() {
    return Array.from(this.list.querySelectorAll('.bx-order-row'));
  },

  bindDrag() {
    let dragged = null;

    // Arm dragging only from the grip handle so clicks on the row controls
    // never turn into accidental drags. Re-armed on every grip press.
    this.list.addEventListener('pointerdown', (e) => {
      const row = e.target.closest('.bx-order-row');
      if (row && e.target.closest('.bx-order-grip')) {
        row.draggable = true;
      }
    });
    document.addEventListener('pointerup', () => {
      this.rows().forEach(r => {
        if (!r.classList.contains('is-dragging')) r.draggable = false;
      });
    });

    this.list.addEventListener('dragstart', (e) => {
      const row = e.target.closest('.bx-order-row');
      if (!row || !row.draggable) return;
      dragged = row;
      row.classList.add('is-dragging');
      try { e.dataTransfer.setData(this.DRAG_KEY, row.dataset.key || ''); } catch (err) { /* legacy */ }
      e.dataTransfer.effectAllowed = 'move';
    });

    this.list.addEventListener('dragover', (e) => {
      if (!dragged) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const target = e.target.closest('.bx-order-row');
      if (!target || target === dragged) return;
      const rect = target.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      target.classList.toggle('is-drop-before', before);
      target.classList.toggle('is-drop-after', !before);
    });

    this.list.addEventListener('drop', (e) => {
      if (!dragged) return;
      e.preventDefault();
      const target = e.target.closest('.bx-order-row');
      if (target && target !== dragged) {
        const before = target.classList.contains('is-drop-before');
        this.list.insertBefore(dragged, before ? target : target.nextSibling);
      }
      this.clearDragMarks();
      dragged.draggable = false;
      dragged.classList.remove('is-dragging');
      this.announceMove(dragged);
      dragged = null;
      this.refresh();
    });

    this.list.addEventListener('dragend', () => {
      if (dragged) {
        dragged.draggable = false;
        dragged.classList.remove('is-dragging');
      }
      this.clearDragMarks();
      dragged = null;
    });
  },

  clearDragMarks() {
    this.list.querySelectorAll('.is-drop-before, .is-drop-after').forEach(r =>
      r.classList.remove('is-drop-before', 'is-drop-after'));
  },

  moveRow(row, delta) {
    if (!row) return;
    const sibling = delta < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    this.list.insertBefore(row, delta < 0 ? sibling : sibling.nextSibling);
    this.announceMove(row);
    this.refresh();
  },

  rowName(row) {
    return ((row && row.querySelector('.bx-order-name')) || {}).textContent || '';
  },

  announceMove(row) {
    const rows = this.rows();
    const idx = rows.indexOf(row) + 1;
    if (idx > 0) {
      this.announce(bxt('orderLiveMoved',
        { name: this.rowName(row), n: idx, total: rows.length }));
    }
  },

  toggleVisibility(row) {
    if (!row) return;
    const hiding = row.dataset.visible !== '0';
    const hiddenCount = this.rows().filter(r => r.dataset.visible === '0').length;
    if (hiding && hiddenCount + 1 >= this.rows().length) {
      this.notify('error', bxt('msgOrderMinVisible'));
      row.classList.add('is-blocked');
      setTimeout(() => row.classList.remove('is-blocked'), 900);
      return;
    }
    this.paintRow(row, hiding ? '0' : '1');
    this.announce(bxt(hiding ? 'orderLiveHidden' : 'orderLiveShown',
      { name: this.rowName(row) }));
    this.refresh();
  },

  paintRow(row, visible) {
    row.dataset.visible = visible;
    row.classList.toggle('is-hidden', visible === '0');
    const eye = row.querySelector('.bx-order-eye');
    if (eye) {
      const hidden = visible === '0';
      eye.setAttribute('aria-pressed', hidden ? 'true' : 'false');
      const name = (row.querySelector('.bx-order-name') || {}).textContent || '';
      eye.setAttribute('aria-label',
        ((hidden ? bxt('orderShowSection') : bxt('orderHideSection')) + ' ' + name).trim());
    }
  },

  applyPreset(rawOrder) {
    if (!rawOrder) return;
    const defaultOrder = (this.list.dataset.defaultOrder || '').split(',').filter(Boolean);
    let keys = rawOrder === '__default__'
      ? defaultOrder
      : String(rawOrder).split(',').map(s => s.trim()).filter(Boolean);
    const byKey = {};
    this.rows().forEach(r => { byKey[r.dataset.key] = r; });
    keys = keys.filter(k => byKey[k]);
    this.rows().forEach(r => { if (!keys.includes(r.dataset.key)) keys.push(r.dataset.key); });
    keys.forEach(key => this.list.appendChild(byKey[key]));
    this.refresh();
  },

  collect() {
    const order = [];
    const visibility = {};
    this.rows().forEach(r => {
      order.push(r.dataset.key);
      visibility[r.dataset.key] = r.dataset.visible !== '0';
    });
    return { order, visibility };
  },

  serialize() {
    return JSON.stringify(this.collect());
  },

  hasPending() {
    return !!this.list && this.serialize() !== this.baseline;
  },

  markBaseline() {
    this.baseline = this.serialize();
    document.body.classList.remove('bx-layout-dirty');
  },

  announce(message) {
    if (this.liveEl && message) this.liveEl.textContent = message;
  },

  isDefaultState() {
    const defaultOrder = (this.list.dataset.defaultOrder || '').split(',').filter(Boolean);
    const { order, visibility } = this.collect();
    const orderMatches = order.length === defaultOrder.length &&
      defaultOrder.every((key, i) => order[i] === key);
    const allVisible = Object.keys(visibility).every(k => visibility[k]);
    return orderMatches && allVisible;
  },

  setStatus() {
    if (!this.status) return;
    const pending = this.hasPending();
    const labelCustom = this.status.dataset.labelCustom || 'Custom layout';
    const labelDefault = this.status.dataset.labelDefault || 'Theme default';
    const labelUnsaved = this.status.dataset.labelUnsaved || bxt('orderStatusUnsaved');
    this.status.classList.toggle('is-custom', !pending && this.serverCustom);
    this.status.classList.toggle('is-unsaved', pending);
    this.status.textContent = pending
      ? labelUnsaved
      : (this.serverCustom ? labelCustom : labelDefault);
  },

  refreshChips() {
    if (!this.chips || !this.chips.length) return;
    const order = this.collect().order.join(',');
    const defaultOrder = this.list.dataset.defaultOrder || '';
    this.chips.forEach(chip => {
      const chipOrder = chip.dataset.order === '__default__' ? defaultOrder : chip.dataset.order;
      const active = chipOrder === order;
      chip.classList.toggle('is-active', active);
      chip.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  },

  refresh() {
    const rows = this.rows();
    rows.forEach((row, i) => {
      const num = row.querySelector('.bx-order-num');
      if (num) num.textContent = i + 1;
      const up = row.querySelector('[data-action="order-up"]');
      const down = row.querySelector('[data-action="order-down"]');
      const disableUp = i === 0;
      const disableDown = i === rows.length - 1;
      // A disabled button drops focus to <body>; hand it to the still-usable
      // sibling so keyboard users stay on the row they were reordering.
      if (up) {
        if (disableUp && document.activeElement === up && down && !disableDown) down.focus();
        up.disabled = disableUp;
      }
      if (down) {
        if (disableDown && document.activeElement === down && up && !disableUp) up.focus();
        down.disabled = disableDown;
      }
    });
    document.body.classList.toggle('bx-layout-dirty', this.hasPending());
    if (this.saveBtn) this.saveBtn.disabled = !this.hasPending();
    this.refreshChips();
    this.setStatus();
    BXAutosave.layoutChanged();
  },

  csrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           document.querySelector('meta[name="csrf-token"]')?.content;
  },

  save() {
    if (!this.saveUrl || this.saving) return;
    if (!this.hasPending()) return;
    this.doSave();
  },

  // Saving is reversible and already an explicit intent, so no confirm step.
  // The modal is reserved for Reset, the one destructive action here.
  reset() {
    if (!this.saveUrl || this.saving) return;
    if (!this.serverCustom && !this.hasPending()) {
      this.notify('info', bxt('msgOrderAlreadyDefault'));
      return;
    }
    if (!this.confirmEl) {
      this.doReset();
      return;
    }
    const title = this.confirmEl.querySelector('#bx-order-confirm-title');
    const desc = this.confirmEl.querySelector('#bx-order-confirm-desc');
    const ok = this.confirmEl.querySelector('[data-action="order-confirm-save"]');
    if (title) title.textContent = bxt('orderConfirmResetTitle');
    if (desc) desc.textContent = bxt('orderConfirmResetDesc');
    if (ok) ok.textContent = bxt('orderConfirmResetOk');
    this.confirmOpener = document.activeElement || this.resetBtn;
    this.confirmEl.classList.add('is-open');
    this.confirmEl.setAttribute('aria-hidden', 'false');
    setTimeout(() => (ok || this.confirmEl).focus(), 60);
  },

  closeConfirm() {
    if (!this.confirmEl) return;
    this.confirmEl.classList.remove('is-open');
    this.confirmEl.setAttribute('aria-hidden', 'true');
    const opener = this.confirmOpener || this.resetBtn;
    if (opener && typeof opener.focus === 'function') opener.focus();
  },

  confirmReset() {
    this.closeConfirm();
    this.doReset();
  },

  showSaved() {
    const el = document.getElementById('bx-order-saved');
    if (!el) {
      this.notify('success', bxt('msgOrderSaved'));
      return;
    }

    clearTimeout(this.savedTimer);
    el.classList.remove('is-leaving');
    el.classList.add('is-open');

    const dismiss = () => {
      if (!el.classList.contains('is-open')) return;
      el.classList.remove('is-open');
      el.classList.add('is-leaving');
      this.savedTimer = setTimeout(() => el.classList.remove('is-leaving'), 260);
    };

    const close = el.querySelector('.bx-order-saved-close');
    if (close) close.onclick = dismiss;

    this.savedTimer = setTimeout(dismiss, 4200);
  },

  async persist() {
    const { order, visibility } = this.collect();
    const body = new URLSearchParams({
      section_order: JSON.stringify(order),
      section_visibility: JSON.stringify(visibility)
    });
    try {
      const res = await fetch(this.saveUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': this.csrfToken(),
                   'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString()
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        let detail = '';
        if (data && data.error) detail = ' — ' + data.error;
        else if (data && Array.isArray(data.invalid_keys) && data.invalid_keys.length) {
          detail = ' — ' + data.invalid_keys.join(', ');
        }
        return { ok: false, detail };
      }
      return { ok: true };
    } catch (err) {
      return { ok: false, network: true };
    }
  },

  // Used by the form submit path: persist pending layout edits so the main
  // "Save changes" never drops them. Returns true when nothing is pending or
  // the save succeeded.
  async flush() {
    if (!this.hasPending()) return true;
    if (this.saving && this.lastSavePromise) {
      const ok = await this.lastSavePromise.catch(() => false);
      if (ok && !this.hasPending()) return true;
    }
    if (!this.hasPending()) return true;
    const { ok } = await this.persist();
    if (ok) {
      this.serverCustom = !this.isDefaultState();
      this.markBaseline();
      this.refresh();
    }
    return ok;
  },

  async doSave() {
    if (this.saving) return;
    const btn = this.saveBtn;
    const original = btn ? btn.innerHTML : '';
    this.saving = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = bxt('orderSaving');
    }
    const run = (async () => {
      const { ok, detail, network } = await this.persist();
      if (!ok) {
        this.notify('error', (network ? bxt('msgNetworkError') : bxt('msgOrderSaveFail')) + (detail || ''));
        return false;
      }
      this.serverCustom = !this.isDefaultState();
      this.markBaseline();
      this.refresh();
      this.showSaved();
      this.announce(bxt('orderLiveSaved'));
      return true;
    })();
    this.lastSavePromise = run;
    try {
      return await run;
    } finally {
      this.saving = false;
      if (btn) {
        btn.innerHTML = original;
        btn.disabled = !this.hasPending();
      }
    }
  },

  async doReset() {
    if (this.saving) return;
    this.saving = true;
    if (this.resetBtn) this.resetBtn.disabled = true;
    try {
      const body = new URLSearchParams({ reset: '1' });
      const res = await fetch(this.saveUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': this.csrfToken(),
                   'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString()
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        this.notify('error', bxt('msgOrderResetFail'));
        return;
      }
      this.applyPreset('__default__');
      this.rows().forEach(r => this.paintRow(r, '1'));
      this.serverCustom = false;
      this.markBaseline();
      this.refresh();
      this.notify('success', bxt('msgOrderReset'));
    } catch (err) {
      this.notify('error', bxt('msgNetworkError'));
    } finally {
      this.saving = false;
      if (this.resetBtn) this.resetBtn.disabled = false;
    }
  },

  notify(type, message) {
    if (window.BX && typeof BX.toast === 'function') {
      BX.toast(message, type);
    } else {
      alert(message);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => BX.init());
