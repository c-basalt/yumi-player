import { type SongEntry } from "@/api/player"

export const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    const secs = Math.floor(seconds % 60)
    return hours > 0 ? `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}` :
        `${mins}:${secs.toString().padStart(2, '0')}`
}

export const formatLargeNumber = (num: number) => {
    if (num < 1000) return `${num}`
    if (num < 10000) return `${(num / 1000).toFixed(1)}k`
    if (num < 100000) return `${(num / 10000).toFixed(1)}w`
    return `${(num / 10000).toFixed(0)}w`
}

export const getEntryTitle = (song: SongEntry | null) => {
    if (!song) return undefined
    const title = song.music.title
    const videoTitle: string | undefined = song.music.meta?.title
    if (!videoTitle || title.length > 3) return title
    return `${title} ${videoTitle}`
}