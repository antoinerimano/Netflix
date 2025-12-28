// canvasWorker.js

self.onmessage = (event) => {
  const { bitmap, originalWidth, originalHeight, scaleFactor } = event.data;

  // Calculate reduced resolution
  const width = originalWidth * scaleFactor;
  const height = originalHeight * scaleFactor;

  if (typeof OffscreenCanvas !== 'undefined') {
    const offscreenCanvas = new OffscreenCanvas(width, height);
    const ctx = offscreenCanvas.getContext('2d', { alpha: false });

    // Draw the ImageBitmap onto the OffscreenCanvas at the reduced resolution
    ctx.drawImage(bitmap, 0, 0, width, height);

    // Convert the OffscreenCanvas to a blob and send it back to the main thread
    offscreenCanvas.convertToBlob().then((blob) => {
      self.postMessage({ blob });
    });
  }
};

