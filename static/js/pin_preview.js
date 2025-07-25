// JavaScript for pin style preview on pin assignment page
(function() {
  const pinDataScript = document.getElementById('pin-data');
  if (!pinDataScript) return;
  const pinData = JSON.parse(pinDataScript.textContent);

  function updatePreview(index) {
    const selectEl = document.getElementById('select_' + index);
    const previewEl = document.getElementById('preview_' + index);
    const selectedPinKey = selectEl.value;
    if (pinData[selectedPinKey]) {
      previewEl.src = pinData[selectedPinKey].url;
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    const selects = document.querySelectorAll('select[id^="select_"]');
    selects.forEach((select, i) => {
      updatePreview(i + 1);
      select.addEventListener('change', () => updatePreview(i + 1));
    });
  });
})();
