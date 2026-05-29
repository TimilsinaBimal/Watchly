export function initializeYearSliderControl() {
    const yearMin = document.getElementById('yearMin');
    const yearMax = document.getElementById('yearMax');
    const yearMinLabel = document.getElementById('yearMinLabel');
    const yearMaxLabel = document.getElementById('yearMaxLabel');
    const track = document.getElementById('yearSliderTrack');

    if (!yearMin || !yearMax || !yearMinLabel || !yearMaxLabel || !track) {
        return () => {};
    }

    function updateSlider() {
        const minVal = parseInt(yearMin.value);
        const maxVal = parseInt(yearMax.value);

        yearMinLabel.textContent = minVal;
        yearMaxLabel.textContent = maxVal;

        const range = yearMin.max - yearMin.min;
        const left = ((minVal - yearMin.min) / range) * 100;
        const right = ((yearMin.max - maxVal) / range) * 100;

        track.style.left = left + '%';
        track.style.right = right + '%';
    }

    yearMin.addEventListener('input', () => {
        if (parseInt(yearMin.value) > parseInt(yearMax.value)) {
            yearMin.value = yearMax.value;
        }
        yearMin.classList.add('year-slider-active');
        yearMax.classList.remove('year-slider-active');
        updateSlider();
    });

    yearMax.addEventListener('input', () => {
        if (parseInt(yearMax.value) < parseInt(yearMin.value)) {
            yearMax.value = yearMin.value;
        }
        yearMax.classList.add('year-slider-active');
        yearMin.classList.remove('year-slider-active');
        updateSlider();
    });

    updateSlider();
    return updateSlider;
}
