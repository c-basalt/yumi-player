const fullWidthRegex = /[\u3000-\u9FFF\uAC00-\uD7FF\uF900-\uFAFF\uFF01-\uFF60]/;

export const cjkWidth = (str: string) => {
    return [...str].map((i) => (fullWidthRegex.test(i) ? 2 : 1)).reduce((sum, c) => sum + c, 0);
};

export const cjkTruncate = (str: string, max: number) => {
    const codeWidth = [...str].map((i) => (fullWidthRegex.test(i) ? 2 : 1));
    const totalWidth = codeWidth.reduce((sum, c) => sum + c, 0);
    if (totalWidth <= max) return str;

    let width = 0;
    for (let i = 0; i < codeWidth.length; i++) {
        width += codeWidth[i];
        if (width > max - 2) {
            return str.slice(0, i).trimEnd() + '…';
        }
    }
    return str;
};
