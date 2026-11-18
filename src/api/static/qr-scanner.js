// Unirse con QR desde el portal del estudiante (HU-Q5: "ingresar el código o
// escanear el QR desde mi cuenta ... sin salir del sistema").
//
// * Usa la cámara con getUserMedia, que el navegador solo permite en
//   contextos seguros (HTTPS o localhost) y con permiso del usuario.
// * Decodifica con el lector nativo `BarcodeDetector` cuando existe (Chrome
//   en Android) y, si no, con jsQR (Apache-2.0, copia local en
//   /assets/vendor/jsQR.js), necesario en Safari para iOS y en Firefox.
// * Del QR solo se toma el código: el ingreso pasa por el mismo endpoint y las
//   mismas validaciones que el código escrito.
//
// Se carga después de app.js y quick-activities.js.

const scanner = { stream: null, frame: null, detector: null, busy: false };

function codeFromQr(text) {
  const raw = (text || "").trim();
  try {
    const url = new URL(raw);
    const code = url.searchParams.get("actividad");
    if (code) return code.trim().toUpperCase();
  } catch {
    // No es un enlace: puede ser el código directamente.
  }
  return /^[A-Za-z0-9-\s]{4,16}$/.test(raw) ? raw.replace(/[^A-Za-z0-9]/g, "").toUpperCase() : "";
}

function loadJsQr() {
  if (window.jsQR) return Promise.resolve(window.jsQR);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/assets/vendor/jsQR.js";
    script.onload = () => (window.jsQR ? resolve(window.jsQR) : reject(new Error("jsQR no cargó")));
    script.onerror = () => reject(new Error("No se pudo cargar el lector de QR."));
    document.head.appendChild(script);
  });
}

async function buildDetector() {
  if ("BarcodeDetector" in window) {
    try {
      const formats = await window.BarcodeDetector.getSupportedFormats();
      if (formats.includes("qr_code")) {
        const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
        return async (video) => (await detector.detect(video))[0]?.rawValue || "";
      }
    } catch {
      // Se usa jsQR.
    }
  }
  const jsQR = await loadJsQr();
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { willReadFrequently: true });
  return async (video) => {
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) return "";
    // Se reduce la imagen para decodificar rápido también en celulares.
    const scale = Math.min(1, 640 / Math.max(width, height));
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    return jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" })?.data || "";
  };
}

function setScannerStatus(message, isError = false) {
  const status = $("#qr-scanner-status");
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}

function stopScanner() {
  if (scanner.frame) cancelAnimationFrame(scanner.frame);
  scanner.frame = null;
  scanner.stream?.getTracks().forEach((track) => track.stop());
  scanner.stream = null;
  const video = $("#qr-scanner-video");
  if (video) video.srcObject = null;
}

function closeScanner() {
  stopScanner();
  const dialog = $("#qr-scanner-dialog");
  if (dialog?.open) dialog.close();
}

async function openScanner() {
  const dialog = $("#qr-scanner-dialog");
  dialog.showModal();
  setScannerStatus("Activando la cámara…");
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    setScannerStatus(
      "Este navegador no permite usar la cámara aquí (se necesita HTTPS). "
      + "Escanea el QR con la cámara del celular o escribe el código.",
      true,
    );
    return;
  }
  try {
    const [stream, detect] = await Promise.all([
      navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false }),
      buildDetector(),
    ]);
    if (!dialog.open) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    scanner.stream = stream;
    const video = $("#qr-scanner-video");
    video.srcObject = stream;
    await video.play();
    setScannerStatus("Apunta al QR que muestra tu docente.");
    const loop = async () => {
      if (!scanner.stream) return;
      if (!scanner.busy) {
        scanner.busy = true;
        try {
          const code = codeFromQr(await detect(video));
          if (code) {
            closeScanner();
            $("#student-join-code").value = code;
            joinActivity(code);
            return;
          }
        } catch {
          // Cuadro ilegible: se intenta con el siguiente.
        } finally {
          scanner.busy = false;
        }
      }
      scanner.frame = requestAnimationFrame(loop);
    };
    loop();
  } catch (error) {
    stopScanner();
    const denied = error?.name === "NotAllowedError" || error?.name === "SecurityError";
    setScannerStatus(
      denied
        ? "No se dio permiso para usar la cámara. Actívalo en el navegador o escribe el código."
        : `No se pudo usar la cámara (${error?.message || error}). Escribe el código.`,
      true,
    );
  }
}

$("#student-scan-button")?.addEventListener("click", openScanner);
$("#qr-scanner-close")?.addEventListener("click", closeScanner);
$("#qr-scanner-dialog")?.addEventListener("close", stopScanner);
