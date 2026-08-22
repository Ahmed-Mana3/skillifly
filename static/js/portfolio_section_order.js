(function () {
    function parseOrder() {
        const dataNode = document.getElementById('sf-section-order-data');
        if (!dataNode) return [];
        try {
            const parsed = JSON.parse(dataNode.textContent || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return [];
        }
    }

    function firstMatch(selectors) {
        for (const selector of selectors) {
            const node = document.querySelector(selector);
            if (node) return node;
        }
        return null;
    }

    function findByHeading(key) {
        const headingKeywords = {
            projects: ['projects', 'work showcase', 'portfolio', 'software projects', 'showcase'],
            skills: ['skills', 'expertise', 'technologies', 'proficiency'],
            experience: ['experience', 'timeline', 'extracurricular'],
            education: ['education', 'academic'],
            links: ['links', 'connect', 'social'],
        };

        const keywords = headingKeywords[key] || [];
        if (!keywords.length) return null;

        const sections = Array.from(document.querySelectorAll('section'));
        let bestMatch = null;
        let bestScore = 0;

        sections.forEach((section) => {
            const idClass = `${section.id} ${section.className}`.toLowerCase();
            if (idClass.includes('hero') || idClass.includes('contact')) return;

            const heading = section.querySelector('h1, h2, h3');
            const text = (heading ? heading.textContent : section.textContent).toLowerCase();
            let score = 0;

            keywords.forEach((keyword) => {
                if (text.includes(keyword)) score += 1;
            });

            if (score > bestScore) {
                bestScore = score;
                bestMatch = section;
            }
        });

        return bestScore > 0 ? bestMatch : null;
    }

    function findSectionForKey(key) {
        const selectors = {
            projects: ['#projects', '#portfolio', '.projects-section', '[data-section="projects"]'],
            skills: ['#skills', '.skills-section', '[data-section="skills"]'],
            experience: ['#experience', '.exp-section', '.experience-section', '[data-section="experience"]'],
            education: ['#education', '.edu-section', '.education-section', '[data-section="education"]'],
            links: ['#links', '#connect', '.links-section', '[data-section="links"]'],
        };

        const matched = firstMatch(selectors[key] || []);
        if (matched) return matched;
        return findByHeading(key);
    }

    function findBestCommonParent(nodes) {
        const bucket = new Map();
        nodes.forEach((node) => {
            if (!node || !node.parentElement) return;
            const parent = node.parentElement;
            bucket.set(parent, (bucket.get(parent) || 0) + 1);
        });

        let target = null;
        let maxCount = 0;
        bucket.forEach((count, parent) => {
            if (count > maxCount) {
                maxCount = count;
                target = parent;
            }
        });

        return target;
    }

    function runSectionOrdering() {
        const order = parseOrder();
        if (!order.length) return;

        const foundByKey = {};
        order.forEach((key) => {
            foundByKey[key] = findSectionForKey(key);
        });

        const foundSections = order
            .map((key) => foundByKey[key])
            .filter((value) => value && value.tagName);

        if (foundSections.length < 2) return;

        const commonParent = findBestCommonParent(foundSections);
        if (!commonParent) return;

        const contactAnchor = firstMatch(['#contact', '.contact-section', '.contact-cta-section']);
        const useContactAnchor = contactAnchor && contactAnchor.parentElement === commonParent;

        order.forEach((key) => {
            const section = foundByKey[key];
            if (!section || section.parentElement !== commonParent) return;

            if (useContactAnchor) {
                commonParent.insertBefore(section, contactAnchor);
            } else {
                commonParent.appendChild(section);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', runSectionOrdering);
    } else {
        runSectionOrdering();
    }
})();
