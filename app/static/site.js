const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#primary-navigation');

if (menuButton && navigation) {
  const closeMenu = () => {
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', menuButton.dataset.labelOpen);
    navigation.classList.remove('is-open');
  };

  menuButton.addEventListener('click', () => {
    const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
    menuButton.setAttribute('aria-expanded', String(!isOpen));
    menuButton.setAttribute('aria-label', isOpen ? menuButton.dataset.labelOpen : menuButton.dataset.labelClose);
    navigation.classList.toggle('is-open', !isOpen);
  });

  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menuButton.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menuButton.focus();
    }
  });
}

const languageToggle = document.querySelector('[data-language-toggle]');

if (languageToggle) {
  languageToggle.addEventListener('click', () => {
    const nextPage = `${window.location.pathname}${window.location.search}`;
    const targetLanguage = languageToggle.dataset.targetLanguage;
    window.location.href = `/language/${targetLanguage}?next=${encodeURIComponent(nextPage)}`;
  });
}

const lightbox = document.querySelector('.image-lightbox');

if (lightbox) {
  const lightboxImage = lightbox.querySelector('img');
  const closeButton = lightbox.querySelector('.lightbox-close');

  document.querySelectorAll('[data-gallery-image]').forEach((thumbnail) => {
    thumbnail.addEventListener('click', () => {
      lightboxImage.src = thumbnail.dataset.galleryImage;
      lightboxImage.alt = thumbnail.dataset.galleryAlt;
      lightbox.showModal();
    });
  });

  closeButton.addEventListener('click', () => lightbox.close());
  lightbox.addEventListener('click', (event) => {
    if (event.target === lightbox) lightbox.close();
  });
  lightbox.addEventListener('close', () => {
    lightboxImage.removeAttribute('src');
    lightboxImage.alt = '';
  });
}

const sectionForms = document.querySelectorAll('form[action="/admin/sections/save"]');

if (sectionForms.length) {
  fetch('/admin/sections/structure')
    .then((response) => response.ok ? response.json() : null)
    .then((structure) => {
      if (!structure) return;

      for (const form of sectionForms) {
        const sectionIdInput = form.querySelector('[name="section_id"]');
        const sectionId = sectionIdInput?.value ?? null;
        const currentSection = sectionId ? structure.sections[sectionId] : null;
        if (sectionId && !currentSection) continue;
        const descendants = new Set();
        if (sectionId) {
          const pending = [Number(sectionId)];
          while (pending.length) {
            const ancestorId = pending.pop();
            for (const [childId, child] of Object.entries(structure.sections)) {
              if (Number(child.parent_id) === ancestorId && !descendants.has(Number(childId))) {
                descendants.add(Number(childId));
                pending.push(Number(childId));
              }
            }
          }
        }
        const label = document.createElement('label');
        label.className = 'wide-field page-placement-label';
        label.append(document.createTextNode('Page placement (choose a parent submenu)'));

        const select = document.createElement('select');
        select.name = 'parent_target';
        const topLevelOption = document.createElement('option');
        topLevelOption.value = '';
        topLevelOption.textContent = 'Top-level tab';
        select.append(topLevelOption);

        for (const parent of structure.parents) {
          if (parent.kind === 'page' && sectionId && String(parent.value) === `page:${sectionId}`) continue;
          if (parent.kind === 'page' && descendants.has(Number(parent.value.slice(5)))) continue;
          const option = document.createElement('option');
          option.value = parent.value;
          option.textContent = parent.path;
          const currentTarget = currentSection?.parent_category_id
            ? `category:${currentSection.parent_category_id}`
            : currentSection?.parent_id ? `page:${currentSection.parent_id}` : '';
          if (currentTarget === parent.value) option.selected = true;
          select.append(option);
        }

        label.append(select);
        const dropdownLabel = document.createElement('label');
        dropdownLabel.className = 'page-dropdown-toggle wide-field';
        const dropdownInput = document.createElement('input');
        dropdownInput.type = 'checkbox';
        dropdownInput.name = 'is_dropdown';
        dropdownInput.checked = Boolean(currentSection?.is_dropdown);
        dropdownLabel.append(dropdownInput, document.createTextNode('Create submenu only (child pages and projects)'));
        const pageFields = form.querySelectorAll('[name="slug"], [name="body"], [name="body_hr"]');
        const updatePageMode = () => {
          pageFields.forEach((field) => {
            field.disabled = dropdownInput.checked;
            field.closest('label')?.classList.toggle('is-disabled', dropdownInput.checked);
          });
        };
        dropdownInput.addEventListener('change', updatePageMode);
        updatePageMode();
        const submitButton = form.querySelector('button[type="submit"]');
        form.insertBefore(label, submitButton ?? null);
        form.insertBefore(dropdownLabel, submitButton ?? null);
      }
    })
    .catch(() => {});
}

const projectForms = document.querySelectorAll('form[action="/admin/projects/save"]');

if (projectForms.length) {
  fetch('/admin/projects/structure')
    .then((response) => response.ok ? response.json() : null)
    .then((structure) => {
      if (!structure) return;

      for (const form of projectForms) {
        const projectId = form.querySelector('[name="project_id"]')?.value ?? null;
        const selectedCategories = projectId ? structure.project_categories[projectId] ?? [] : [];
        const legacyCategory = form.querySelector('[name="category_id"]')?.value;
        if (legacyCategory && !selectedCategories.length) selectedCategories.push(Number(legacyCategory));

        const categorySelect = form.querySelector('[name="category_id"]');
        if (categorySelect) {
          const fieldset = document.createElement('fieldset');
          fieldset.className = 'project-assignment-fieldset';
          const legend = document.createElement('legend');
          legend.textContent = 'Categories (information only)';
          fieldset.append(legend);
          for (const category of structure.categories) {
            const label = document.createElement('label');
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.name = 'category_ids';
            input.value = category.id;
            input.checked = selectedCategories.includes(category.id);
            label.append(input, document.createTextNode(category.name));
            fieldset.append(label);
          }
          categorySelect.closest('label').replaceWith(fieldset);
        }

        const destinationFieldset = document.createElement('fieldset');
        destinationFieldset.className = 'project-assignment-fieldset wide-field';
        const destinationLegend = document.createElement('legend');
        destinationLegend.textContent = 'Show this project on pages';
        destinationFieldset.append(destinationLegend);
        const selectedSections = projectId ? structure.project_sections[projectId] ?? [] : [];
        for (const section of structure.sections) {
          const label = document.createElement('label');
          const input = document.createElement('input');
          input.type = 'checkbox';
          input.name = 'section_ids';
          input.value = section.id;
          input.checked = selectedSections.includes(section.id);
          label.append(input, document.createTextNode(section.path ?? section.title));
          destinationFieldset.append(label);
        }
        const submitButton = form.querySelector('button[type="submit"]');
        form.insertBefore(destinationFieldset, submitButton ?? null);
      }
    })
    .catch(() => {});
}
