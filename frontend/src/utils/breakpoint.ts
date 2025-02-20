import { useBreakpoints } from '@vueuse/core';

export const breakpoints = useBreakpoints({ mobile: 640, tablet: 1024 });
export const isMobile = breakpoints.smaller('mobile');
export const isTablet = breakpoints.between('mobile', 'tablet');
