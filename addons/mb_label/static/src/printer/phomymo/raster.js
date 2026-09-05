// Vendored from phomymo, unmodified except where marked "mb:".
// https://github.com/transcriptionstream/phomymo @ 1f58d3f (2026-05-17), ISC.
// Do not edit to fix a bug here - fix it upstream and re-vendor, or the next
// re-vendor silently undoes it.
// @ts-nocheck
//
// mb: lifted from canvas.js lines 1885-2248, which is a class; the
// methods are standalone functions here and `this._x(` reads `_x(`. Bodies are
// byte-for-byte upstream.

import { printerProtocolDebug } from './debug.js';

/**
 * Convert RGBA pixels to perceptual grayscale with gamma correction
 * @param {Uint8ClampedArray} pixels - RGBA pixel data
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @param {number} gamma - Gamma correction value (1.0 = none, 1.3 = lighter midtones for thermal)
 * @returns {Float32Array} Grayscale values 0-255
 */
function _rgbaToGrayscale(pixels, width, height, gamma = 1.3) {
  const grayscale = new Float32Array(width * height);
  const gammaInv = 1.0 / gamma;

  for (let i = 0; i < width * height; i++) {
    const idx = i * 4;
    const r = pixels[idx];
    const g = pixels[idx + 1];
    const b = pixels[idx + 2];
    const a = pixels[idx + 3];

    // Perceptual grayscale (ITU-R BT.601)
    let gray = 0.299 * r + 0.587 * g + 0.114 * b;

    // Handle transparency - blend with white background
    if (a < 255) {
      gray = gray * (a / 255) + 255 * (1 - a / 255);
    }

    // Apply gamma correction to lift midtones for thermal printing
    gray = 255 * Math.pow(gray / 255, gammaInv);

    grayscale[i] = gray;
  }

  return grayscale;
}

/**
 * Apply Floyd-Steinberg dithering to grayscale image
 * Produces high-quality 1-bit output that simulates grayscale through dot patterns
 * @param {Float32Array} grayscale - Grayscale values 0-255
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @returns {Uint8Array} 1-bit values (0 = white, 1 = black)
 */
function _floydSteinbergDither(grayscale, width, height) {
  // Work on a copy to avoid modifying original
  const pixels = new Float32Array(grayscale);
  const output = new Uint8Array(width * height);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const oldPixel = pixels[idx];

      // Threshold to black (0) or white (255)
      const newPixel = oldPixel < 128 ? 0 : 255;
      output[idx] = newPixel === 0 ? 1 : 0; // 1 = black, 0 = white

      // Calculate quantization error
      const error = oldPixel - newPixel;

      // Distribute error to neighboring pixels (Floyd-Steinberg pattern)
      //       X   7/16
      // 3/16 5/16 1/16
      if (x + 1 < width) {
        pixels[idx + 1] += error * 7 / 16;
      }
      if (y + 1 < height) {
        if (x > 0) {
          pixels[(y + 1) * width + (x - 1)] += error * 3 / 16;
        }
        pixels[(y + 1) * width + x] += error * 5 / 16;
        if (x + 1 < width) {
          pixels[(y + 1) * width + (x + 1)] += error * 1 / 16;
        }
      }
    }
  }

  return output;
}

/**
 * Apply Atkinson dithering to grayscale image
 * Lighter result than Floyd-Steinberg, good for preserving detail
 * Only distributes 6/8 of error (loses some darkness)
 * @param {Float32Array} grayscale - Grayscale values 0-255
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @returns {Uint8Array} 1-bit values (0 = white, 1 = black)
 */
function _atkinsonDither(grayscale, width, height) {
  const pixels = new Float32Array(grayscale);
  const output = new Uint8Array(width * height);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const oldPixel = pixels[idx];

      const newPixel = oldPixel < 128 ? 0 : 255;
      output[idx] = newPixel === 0 ? 1 : 0;

      // Atkinson only distributes 6/8 of the error (intentionally loses 2/8)
      const error = (oldPixel - newPixel) / 8;

      // Distribute error to 6 neighbors (1/8 each)
      //       X   1   1
      //   1   1   1
      //       1
      if (x + 1 < width) {
        pixels[idx + 1] += error;
      }
      if (x + 2 < width) {
        pixels[idx + 2] += error;
      }
      if (y + 1 < height) {
        if (x > 0) {
          pixels[(y + 1) * width + (x - 1)] += error;
        }
        pixels[(y + 1) * width + x] += error;
        if (x + 1 < width) {
          pixels[(y + 1) * width + (x + 1)] += error;
        }
      }
      if (y + 2 < height) {
        pixels[(y + 2) * width + x] += error;
      }
    }
  }

  return output;
}

/**
 * Apply ordered (Bayer) dithering to grayscale image
 * Creates regular pattern, good for graphics and when consistency matters
 * @param {Float32Array} grayscale - Grayscale values 0-255
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @returns {Uint8Array} 1-bit values (0 = white, 1 = black)
 */
function _orderedDither(grayscale, width, height) {
  const output = new Uint8Array(width * height);

  // 8x8 Bayer matrix (normalized to 0-63, we scale to 0-255)
  const bayer8x8 = [
     0, 32,  8, 40,  2, 34, 10, 42,
    48, 16, 56, 24, 50, 18, 58, 26,
    12, 44,  4, 36, 14, 46,  6, 38,
    60, 28, 52, 20, 62, 30, 54, 22,
     3, 35, 11, 43,  1, 33,  9, 41,
    51, 19, 59, 27, 49, 17, 57, 25,
    15, 47,  7, 39, 13, 45,  5, 37,
    63, 31, 55, 23, 61, 29, 53, 21
  ];

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const gray = grayscale[idx];

      // Get threshold from Bayer matrix (scale from 0-63 to 0-255)
      const bayerIdx = (y % 8) * 8 + (x % 8);
      const threshold = (bayer8x8[bayerIdx] / 64) * 255;

      // Compare pixel to threshold
      output[idx] = gray < threshold ? 1 : 0;
    }
  }

  return output;
}

/**
 * Detect if image likely contains photos or gradients that benefit from dithering
 * @param {Uint8ClampedArray} pixels - RGBA pixel data
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @returns {boolean} True if dithering recommended
 */
function _shouldUseDithering(pixels, width, height) {
  // Sample pixels to check for gradients/photos
  const sampleSize = Math.min(1000, width * height);
  const step = Math.floor((width * height) / sampleSize);

  let uniqueColors = new Set();
  let gradientCount = 0;
  let lastGray = -1;

  for (let i = 0; i < width * height; i += step) {
    const idx = i * 4;
    const r = pixels[idx];
    const g = pixels[idx + 1];
    const b = pixels[idx + 2];

    // Count unique colors (packed RGB)
    uniqueColors.add((r << 16) | (g << 8) | b);

    // Check for gradual transitions (indicates gradients/photos)
    const gray = Math.round((r + g + b) / 3);
    if (lastGray >= 0) {
      const diff = Math.abs(gray - lastGray);
      if (diff > 0 && diff < 30) {
        gradientCount++;
      }
    }
    lastGray = gray;
  }

  // Use dithering if many colors or gradual transitions detected
  const hasManyfColors = uniqueColors.size > 50;
  const hasGradients = gradientCount > sampleSize * 0.1;

  return hasManyfColors || hasGradients;
}

/**
 * Convert pixel data to raster bytes using simple threshold
 * Best for text, barcodes, and simple graphics
 * @param {Uint8ClampedArray} pixels - RGBA pixel data
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @param {number} outputWidthBytes - Output width in bytes (for alignment)
 * @param {'left' | 'center' | 'right'} alignment - How to align output within outputWidthBytes
 */
function _pixelsToRasterThreshold(pixels, width, height, outputWidthBytes, alignment = 'left') {
  const canvasBytesPerRow = Math.ceil(width / 8);
  const output = new Uint8Array(outputWidthBytes * height);

  // Calculate offset based on alignment
  let offset = 0;
  if (alignment === 'center') {
    offset = Math.floor((outputWidthBytes - canvasBytesPerRow) / 2);
  } else if (alignment === 'right') {
    offset = outputWidthBytes - canvasBytesPerRow;
  }

  for (let y = 0; y < height; y++) {
    for (let byteX = 0; byteX < canvasBytesPerRow; byteX++) {
      let byte = 0;

      for (let bit = 0; bit < 8; bit++) {
        const x = byteX * 8 + bit;
        if (x >= width) continue;

        const idx = (y * width + x) * 4;
        const r = pixels[idx];
        const g = pixels[idx + 1];
        const b = pixels[idx + 2];
        // Use perceptual grayscale even for threshold
        const brightness = 0.299 * r + 0.587 * g + 0.114 * b;

        if (brightness < 128) {
          byte |= (1 << (7 - bit));
        }
      }

      const outputPos = y * outputWidthBytes + offset + byteX;
      if (outputPos >= 0 && outputPos < output.length) {
        output[outputPos] = byte;
      }
    }
  }

  return output;
}

/**
 * Convert pixel data to raster bytes using dithering
 * Best for images with gradients, photos, or many colors
 * @param {Uint8ClampedArray} pixels - RGBA pixel data
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @param {number} outputWidthBytes - Output width in bytes (for alignment)
 * @param {'left' | 'center' | 'right'} alignment - How to align output within outputWidthBytes
 * @param {string} algorithm - Dithering algorithm ('floyd-steinberg', 'atkinson', 'ordered')
 */
function _pixelsToRasterDithered(pixels, width, height, outputWidthBytes, alignment = 'left', algorithm = 'floyd-steinberg') {
  // Convert to grayscale with gamma correction
  const grayscale = _rgbaToGrayscale(pixels, width, height, 1.3);

  // Apply selected dithering algorithm
  let dithered;
  switch (algorithm) {
    case 'atkinson':
      dithered = _atkinsonDither(grayscale, width, height);
      break;
    case 'ordered':
      dithered = _orderedDither(grayscale, width, height);
      break;
    case 'floyd-steinberg':
    default:
      dithered = _floydSteinbergDither(grayscale, width, height);
      break;
  }

  // Pack into bytes
  const canvasBytesPerRow = Math.ceil(width / 8);
  const output = new Uint8Array(outputWidthBytes * height);

  // Calculate offset based on alignment
  let offset = 0;
  if (alignment === 'center') {
    offset = Math.floor((outputWidthBytes - canvasBytesPerRow) / 2);
  } else if (alignment === 'right') {
    offset = outputWidthBytes - canvasBytesPerRow;
  }

  for (let y = 0; y < height; y++) {
    for (let byteX = 0; byteX < canvasBytesPerRow; byteX++) {
      let byte = 0;

      for (let bit = 0; bit < 8; bit++) {
        const x = byteX * 8 + bit;
        if (x >= width) continue;

        if (dithered[y * width + x] === 1) {
          byte |= (1 << (7 - bit));
        }
      }

      const outputPos = y * outputWidthBytes + offset + byteX;
      if (outputPos >= 0 && outputPos < output.length) {
        output[outputPos] = byte;
      }
    }
  }

  return output;
}

/**
 * Convert pixel data to raster bytes
 * @param {Uint8ClampedArray} pixels - RGBA pixel data
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @param {number} outputWidthBytes - Output width in bytes (for alignment)
 * @param {'left' | 'center' | 'right'} alignment - How to align output within outputWidthBytes
 * @param {string} ditherMode - Dither mode: 'auto', 'none', 'threshold', 'floyd-steinberg', 'atkinson', 'ordered'
 */
function _pixelsToRaster(pixels, width, height, outputWidthBytes, alignment = 'left', ditherMode = 'auto') {
  // Handle explicit modes
  if (ditherMode === 'none' || ditherMode === 'threshold') {
    printerProtocolDebug('Using threshold method for crisp output');
    return _pixelsToRasterThreshold(pixels, width, height, outputWidthBytes, alignment);
  }

  if (ditherMode === 'floyd-steinberg' || ditherMode === 'atkinson' || ditherMode === 'ordered') {
    printerProtocolDebug(`Using ${ditherMode} dithering`);
    return _pixelsToRasterDithered(pixels, width, height, outputWidthBytes, alignment, ditherMode);
  }

  // Auto-detect whether to use dithering based on image content
  const useDithering = _shouldUseDithering(pixels, width, height);

  if (useDithering) {
    printerProtocolDebug('Auto: Using Floyd-Steinberg dithering for better image quality');
    return _pixelsToRasterDithered(pixels, width, height, outputWidthBytes, alignment, 'floyd-steinberg');
  } else {
    printerProtocolDebug('Auto: Using threshold method for crisp text/graphics');
    return _pixelsToRasterThreshold(pixels, width, height, outputWidthBytes, alignment);
  }
}

export { _pixelsToRaster, _pixelsToRasterThreshold, _pixelsToRasterDithered };
