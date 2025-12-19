// static/mapa-matriculas.js — Mapa interactivo de provincias (Matriculados)
document.addEventListener("DOMContentLoaded", () => {
  const svgMapa = document.getElementById("mapa-ecuador");
  if (!svgMapa) {
    console.warn("mapa-matriculas.js: no se encontró #mapa-ecuador");
    return;
  }

  // Panel de detalle (opcional, si existe en el HTML)
  const detalleNombre = document.querySelector(".detalle-provincia h2");
  const detalleTexto = document.querySelector(".detalle-provincia p");
  const detalleImg   = document.querySelector(".detalle-provincia img");

  // ───────────────────── OBTENER NOMBRE DESDE CADA ELEMENTO ─────────────────────
  function obtenerNombreProvincia(el) {
    if (!el) return "";

    // 1) data-nombre / data-provincia
    const dataNombre =
      el.getAttribute("data-nombre") || el.getAttribute("data-provincia");
    if (dataNombre) return dataNombre;

    // 2) Si es un <circle> dentro de label_points, usar la primera clase
    if (el.tagName.toLowerCase() === "circle" && el.classList.length > 0) {
      return el.classList[0]; // p.ej. "Pichincha", "Esmeraldas"
    }

    // 3) Fallback: id
    return el.id || "";
  }

  function slugProvincia(nombre) {
    // Para imágenes opcionales /static/provincias/<slug>.jpg
    return nombre
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\s+/g, "-");
  }

  // ───────────────────── SELECCIONAR UNA PROVINCIA ─────────────────────
  function seleccionarProvincia(el) {
    if (!el) return;

    const nombre = obtenerNombreProvincia(el);
    if (!nombre) {
      console.warn("seleccionarProvincia: no se pudo obtener nombre para", el);
      return;
    }

    console.log("Provincia clickeada en el mapa:", nombre);

    // Quitar selección previa (paths, polygons, círculos)
    svgMapa
      .querySelectorAll(".provincia, path, polygon, #label_points circle")
      .forEach((p) => p.classList.remove("selected"));

    // Marcar seleccionada
    el.classList.add("selected");

    // Actualizar panel de detalle (si existe)
    if (detalleNombre) detalleNombre.textContent = nombre;
    if (detalleTexto)
      detalleTexto.textContent =
        "Oferta y matrícula agregadas para la provincia de " + nombre + ".";
    if (detalleImg) {
      const slug = slugProvincia(nombre);
      detalleImg.src = "/static/provincias/" + slug + ".jpg";
      detalleImg.alt = "Provincia de " + nombre;
    }

    // 👉 Aquí es donde se sincroniza con el dashboard de Matriculados
    if (typeof window.setProvinciaDesdeMapa === "function") {
      window.setProvinciaDesdeMapa(nombre);
    } else {
      console.warn(
        "mapa-matriculas.js: window.setProvinciaDesdeMapa no está definido."
      );
    }
  }

  // ───────────────────── LISTENERS – MAPA CLICKEABLE ─────────────────────
  // Consideramos:
  //  - paths/polygons con class="provincia" (si los tienes)
  //  - círculos dentro de <g id="label_points"> (como en tu SVG)
  const provincias = svgMapa.querySelectorAll(
    ".provincia, #label_points circle"
  );

  provincias.forEach((provEl) => {
    const nombre = obtenerNombreProvincia(provEl);

    // Hover: solo mostramos el nombre
    provEl.addEventListener("mouseenter", () => {
      if (detalleNombre && nombre) {
        detalleNombre.textContent = nombre;
      }
    });

    // Click: selecciona y actualiza datos
    provEl.addEventListener("click", () => {
      seleccionarProvincia(provEl);
    });
  });

  // Si tu SVG ya marca alguna provincia con class="selected", la activamos al inicio
  const inicial =
    svgMapa.querySelector(".provincia.selected") ||
    svgMapa.querySelector("#label_points circle.selected");
  if (inicial) {
    seleccionarProvincia(inicial);
  }
});
