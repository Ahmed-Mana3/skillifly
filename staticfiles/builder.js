// builder.js - Simplified version with Django handling data

// Add Skills
document.getElementById('addSkillBtn').addEventListener('click', function(e) {
    e.preventDefault();
    const skillsList = document.getElementById('skillsList');
    const skillItem = document.createElement('div');
    skillItem.className = 'skill-item';
    skillItem.innerHTML = `
        <input type="text" class="skill-input" name="skills[]" placeholder="e.g., Python, JavaScript, UI Design" required>
        <button type="button" class="btn-remove">Remove</button>
    `;
    skillsList.appendChild(skillItem);
    
    skillItem.querySelector('.btn-remove').addEventListener('click', function(e) {
        e.preventDefault();
        skillItem.remove();
    });
});

// Remove skill
document.querySelectorAll('#skillsList .btn-remove').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        this.closest('.skill-item').remove();
    });
});

// Add Education
document.getElementById('addEducationBtn').addEventListener('click', function(e) {
    e.preventDefault();
    const educationList = document.getElementById('educationList');
    const educationItem = document.createElement('div');
    educationItem.className = 'education-item';
    educationItem.innerHTML = `
        <div class="form-row">
            <div class="form-group">
                <label>School/University</label>
                <input type="text" name="education_school[]" placeholder="Port Said University" required>
            </div>
            <div class="form-group">
                <label>Degree</label>
                <input type="text" name="education_degree[]" placeholder="Bachelor's Degree" required>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Field of Study</label>
                <input type="text" name="education_field[]" placeholder="Computer Science" required>
            </div>
            <div class="form-group">
                <label>Graduation Year</label>
                <input type="number" name="education_year[]" placeholder="2024" required>
            </div>
        </div>
        <button type="button" class="btn-remove">Remove</button>
    `;
    educationList.appendChild(educationItem);
    
    educationItem.querySelector('.btn-remove').addEventListener('click', function(e) {
        e.preventDefault();
        educationItem.remove();
    });
});

// Remove education
document.querySelectorAll('#educationList .btn-remove').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        this.closest('.education-item').remove();
    });
});

// Add Experience
document.getElementById('addExperienceBtn').addEventListener('click', function(e) {
    e.preventDefault();
    const experienceList = document.getElementById('experienceList');
    const experienceItem = document.createElement('div');
    experienceItem.className = 'experience-item';
    experienceItem.innerHTML = `
        <div class="form-row">
            <div class="form-group">
                <label>Job Title</label>
                <input type="text" name="experience_title[]" placeholder="Full Stack Developer" required>
            </div>
            <div class="form-group">
                <label>Company</label>
                <input type="text" name="experience_company[]" placeholder="Tech Company" required>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Start Date</label>
                <input type="month" name="experience_start[]" required>
            </div>
            <div class="form-group">
                <label>End Date</label>
                <input type="month" name="experience_end[]" placeholder="Leave blank if current">
            </div>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea name="experience_description[]" rows="3" placeholder="Describe your role and achievements..." style="font-family: inherit; resize: vertical;"></textarea>
        </div>
        <button type="button" class="btn-remove">Remove</button>
    `;
    experienceList.appendChild(experienceItem);
    
    experienceItem.querySelector('.btn-remove').addEventListener('click', function(e) {
        e.preventDefault();
        experienceItem.remove();
    });
});

// Remove experience
document.querySelectorAll('#experienceList .btn-remove').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        this.closest('.experience-item').remove();
    });
});

// Add Links
document.getElementById('addLinkBtn').addEventListener('click', function(e) {
    e.preventDefault();
    const linksList = document.getElementById('linksList');
    const linkItem = document.createElement('div');
    linkItem.className = 'link-item';
    linkItem.innerHTML = `
        <div class="form-row">
            <div class="form-group">
                <label>Link Name</label>
                <input type="text" name="link_name[]" placeholder="e.g., GitHub, LinkedIn, Portfolio" required>
            </div>
            <div class="form-group">
                <label>URL</label>
                <input type="url" name="link_url[]" placeholder="https://example.com" required>
            </div>
        </div>
        <button type="button" class="btn-remove">Remove</button>
    `;
    linksList.appendChild(linkItem);
    
    linkItem.querySelector('.btn-remove').addEventListener('click', function(e) {
        e.preventDefault();
        linkItem.remove();
    });
});

// Remove links
document.querySelectorAll('#linksList .btn-remove').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        this.closest('.link-item').remove();
    });
});

// Add Projects
document.getElementById('addProjectBtn').addEventListener('click', function(e) {
    e.preventDefault();
    const projectsList = document.getElementById('projectsList');
    const projectItem = document.createElement('div');
    projectItem.className = 'project-item';
    projectItem.innerHTML = `
        <div class="form-row">
            <div class="form-group">
                <label>Project Name</label>
                <input type="text" name="project_name[]" placeholder="e.g., Portfolio Builder" required>
            </div>
            <div class="form-group">
                <label>Project URL (optional)</label>
                <input type="url" name="project_url[]" placeholder="https://example.com">
            </div>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea name="project_description[]" rows="3" placeholder="What did you build? What impact did it have?" style="font-family: inherit; resize: vertical;"></textarea>
        </div>
        <button type="button" class="btn-remove">Remove</button>
    `;
    projectsList.appendChild(projectItem);
    
    projectItem.querySelector('.btn-remove').addEventListener('click', function(e) {
        e.preventDefault();
        projectItem.remove();
    });
});

// Remove project
document.querySelectorAll('#projectsList .btn-remove').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        this.closest('.project-item').remove();
    });
});

// Note: Form submission is handled by Django - no localStorage needed
