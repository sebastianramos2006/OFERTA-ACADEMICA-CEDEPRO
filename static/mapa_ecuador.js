// static/mapa_ecuador.js
document.addEventListener("DOMContentLoaded", () => {
  const wrapper = document.getElementById("mapa-wrapper");
  const svg = document.getElementById("mapa-ecuador");
  const tooltip = document.getElementById("mapa-tooltip");

  if (!wrapper || !svg || !tooltip) {
    console.warn("Mapa Ecuador: faltan elementos en el DOM.");
    return;
  }

  const paths = svg.querySelectorAll("path[id]");

  function mostrarTooltip(evt) {
    const target = evt.target;
    const provincia =
      target.getAttribute("name") ||
      target.id ||
      "Provincia";

    tooltip.textContent = provincia;

    // Posicionar tooltip relativo al contenedor del mapa
    const rectWrapper = wrapper.getBoundingClientRect();
    const x = evt.clientX - rectWrapper.left;
    const y = evt.clientY - rectWrapper.top;

    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
    tooltip.style.display = "block";
  }

  function ocultarTooltip() {
    tooltip.style.display = "none";
  }

  paths.forEach((path) => {
    // Tooltip con hover / movimiento
    path.addEventListener("mouseenter", mostrarTooltip);
    path.addEventListener("mousemove", mostrarTooltip);
    path.addEventListener("mouseleave", ocultarTooltip);

    // Click en provincia: conecta con matriculas.js
    path.addEventListener("click", (evt) => {
      const provinciaRaw =
        evt.target.getAttribute("name") || evt.target.id;

      if (!provinciaRaw) {
        console.warn("Click en provincia sin nombre/id válido");
        return;
      }

      const provincia = provinciaRaw.toString().trim();
      console.log("Provincia clickeada en mapa:", provincia);

      // 1) Intentar usar la función global definida en matriculas.js
      if (typeof window.setProvinciaDesdeMapa === "function") {
        window.setProvinciaDesdeMapa(provincia);
        return;
      }

      // 2) Fallback: usar el hook cedeproMatriculas, si existe
      if (
        window.cedeproMatriculas &&
        typeof window.cedeproMatriculas.setProvincia === "function"
      ) {
        window.cedeproMatriculas.setProvincia(provincia);
        return;
      }

      // 3) Si no hay nada, solo avisar en consola
      console.warn(
        "No se encontró ningún hook global para recibir la provincia desde el mapa."
      );
    });

    // Opcional: cambiar el cursor a manito
    path.style.cursor = "pointer";
  });
});
