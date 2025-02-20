export const endpoint = import.meta.env.DEV
    ? 'http://127.0.0.1:9823/api'
    : `${window.location.origin}/api`;

export async function requestJSON(path: string, options?: RequestInit) {
    const response = await fetch(`${endpoint}${path}`, options);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Request failed');
    }
    return response.json();
}
