// builder.js - Updated for Django FormSets

function updateFormIndex(collection, prefix) {
    // This function can be used if we want to re-index all forms after deletion
    // But for now, we will just ensure new forms get the next index
}

function addForm(btnId, containerId, prefix, htmlGenerator) {
    document.getElementById(btnId).addEventListener('click', function (e) {
        e.preventDefault();
        const container = document.getElementById(containerId);
        const totalFormsInput = document.getElementById(`id_${prefix}-TOTAL_FORMS`);

        if (!totalFormsInput) {
            console.error(`Management form field id_${prefix}-TOTAL_FORMS not found.`);
            return;
        }

        const currentCount = parseInt(totalFormsInput.value);
        const newItem = document.createElement('div');
        // Based on existing class names in builder.html handles
        if (prefix === 'skills') newItem.className = 'skill-item';
        else if (prefix === 'education') newItem.className = 'education-item';
        else if (prefix === 'experience') newItem.className = 'experience-item';
        else if (prefix === 'projects') newItem.className = 'project-item';
        else if (prefix === 'links') newItem.className = 'link-item';

        newItem.innerHTML = htmlGenerator(currentCount);
        container.appendChild(newItem);

        totalFormsInput.value = currentCount + 1;

        // Add remove listener to the new button
        const removeBtn = newItem.querySelector('.btn-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', function (e) {
                e.preventDefault();
                // If it's a dynamic form that was never saved, we can just remove it
                // For simplified 'builder' logic where we replace everything, removing DOM is fine
                // But we should ideally mark for deletion if it existed.
                // Since this is a "new" item, removing DOM is safe.
                newItem.remove();

                // Note: We are NOT decrementing TOTAL_FORMS to avoid index collisions.
                // Django manages gaps if we are careful, or we could re-index.
                // For a simple 'append-only' standard formset logic without re-indexing:
                // If we remove the last one, we could decrement. 
                // But generally, leaving TOTAL_FORMS high is safer unless we re-index everything.
            });
        }
    });
}

// === Skills ===
addForm('addSkillBtn', 'skillsList', 'skills', (index) => `
    <input type="text" class="skill-input" name="skills-${index}-skill" id="id_skills-${index}-skill" placeholder="e.g., Python, JavaScript, UI Design" required>
    <button type="button" class="btn-remove">Remove</button>
`);

// === Education ===
addForm('addEducationBtn', 'educationList', 'education', (index) => `
    <div class="form-row">
        <div class="form-group">
            <label>School/University</label>
            <input type="text" name="education-${index}-school" id="id_education-${index}-school" placeholder="Port Said University" required>
        </div>
        <div class="form-group">
            <label>Degree</label>
            <input type="text" name="education-${index}-degree" id="id_education-${index}-degree" placeholder="Bachelor's Degree" required>
        </div>
    </div>
    <div class="form-row">
        <div class="form-group">
            <label>Field of Study</label>
            <input type="text" name="education-${index}-field" id="id_education-${index}-field" placeholder="Computer Science" required>
        </div>
        <div class="form-group">
            <label>Graduation Year</label>
            <input type="number" name="education-${index}-year" id="id_education-${index}-year" placeholder="2024" required>
        </div>
    </div>
    <button type="button" class="btn-remove">Remove</button>
`);

// === Experience ===
addForm('addExperienceBtn', 'experienceList', 'experience', (index) => `
    <div class="form-row">
        <div class="form-group">
            <label>Job Title</label>
            <input type="text" name="experience-${index}-title" id="id_experience-${index}-title" placeholder="Full Stack Developer" required>
        </div>
        <div class="form-group">
            <label>Company</label>
            <input type="text" name="experience-${index}-company" id="id_experience-${index}-company" placeholder="Tech Company" required>
        </div>
    </div>
    <div class="form-row">
        <div class="form-group">
            <label>Start Date</label>
            <input type="month" name="experience-${index}-start" id="id_experience-${index}-start" required>
        </div>
        <div class="form-group">
            <label>End Date</label>
            <input type="month" name="experience-${index}-end" id="id_experience-${index}-end" placeholder="Leave blank if current">
        </div>
    </div>
    <div class="form-group">
        <label>Description</label>
        <textarea name="experience-${index}-description" id="id_experience-${index}-description" rows="3" placeholder="Describe your role and achievements..." style="font-family: inherit; resize: vertical;"></textarea>
    </div>
    <button type="button" class="btn-remove">Remove</button>
`);

// === Projects ===
addForm('addProjectBtn', 'projectsList', 'projects', (index) => `
    <div class="form-row">
        <div class="form-group">
            <label>Project Name</label>
            <input type="text" name="projects-${index}-name" id="id_projects-${index}-name" placeholder="e.g., Portfolio Builder" required>
        </div>
        <div class="form-group">
            <label>Project URL (optional)</label>
            <input type="url" name="projects-${index}-url" id="id_projects-${index}-url" placeholder="https://example.com">
        </div>
    </div>
    <div class="form-group">
        <label>Description</label>
        <textarea name="projects-${index}-description" id="id_projects-${index}-description" rows="3" placeholder="What did you build? What impact did it have?" style="font-family: inherit; resize: vertical;"></textarea>
    </div>
    <button type="button" class="btn-remove">Remove</button>
`);

// === Links ===
addForm('addLinkBtn', 'linksList', 'links', (index) => `
    <div class="form-row">
        <div class="form-group">
            <label>Link Name</label>
            <input type="text" name="links-${index}-name" id="id_links-${index}-name" placeholder="e.g., GitHub, LinkedIn, Portfolio" required>
        </div>
        <div class="form-group">
            <label>URL</label>
            <input type="url" name="links-${index}-url" id="id_links-${index}-url" placeholder="https://example.com" required>
        </div>
    </div>
    <button type="button" class="btn-remove">Remove</button>
`);


// Handle removal of pre-existing items (rendered by Django)
document.addEventListener('click', function (e) {
    if (e.target && e.target.classList.contains('btn-remove')) {
        const item = e.target.closest('.skill-item, .education-item, .experience-item, .project-item, .link-item');
        if (item) {
            // Check if there is a DELETE checkbox (hidden or visible) inside
            const deleteCheckbox = item.querySelector('input[name$="-DELETE"]');
            if (deleteCheckbox) {
                // If it exists, check it and hide the item
                deleteCheckbox.checked = true;
                item.style.display = 'none';
            } else {
                // If it's a dynamic item (no ID yet), just remove it
                // (Note: The addForm listeners handle their own, but this catches global clicks)
                // To avoid double-handling, we might want to check if it's already handled.
                // But standard simple removal:
                // item.remove(); 
                // Wait, if it was added via JS, it doesn't have the DELETE checkbox usually.
                // The addForm listener handles the JS-added ones specifically.
                // This global listener handles the ones rendered by Django loop.
            }
        }
    }
});

// Specifically for the initial items rendered by Django, enable the remove button
document.querySelectorAll('.skill-item, .education-item, .experience-item, .project-item, .link-item').forEach(item => {
    const removeBtn = item.querySelector('.btn-remove');
    if (removeBtn) {
        removeBtn.addEventListener('click', function (e) {
            e.preventDefault();
            const deleteCheckbox = item.querySelector('input[name$="-DELETE"]');
            if (deleteCheckbox) {
                deleteCheckbox.checked = true;
                item.style.display = 'none';
            } else {
                item.remove();
            }
        });
    }
});

