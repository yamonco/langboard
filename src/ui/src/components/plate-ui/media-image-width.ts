const MAX_INITIAL_IMAGE_WIDTH = 672;

export const getInitialImageWidth = (image: HTMLImageElement) => Math.min(image.naturalWidth, image.clientWidth, MAX_INITIAL_IMAGE_WIDTH);
