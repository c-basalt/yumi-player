import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { getBaseUrl } from '@/api/config'


export const usePlayerUrl = () => {
    const playerBaseUrl = ref(window.location.href)
    const router = useRouter()

    const playerUrl = computed(() => new URL(router.resolve({ name: 'player' }).href, playerBaseUrl.value).href)

    onMounted(() => getBaseUrl().then(url => playerBaseUrl.value = url))

    return { playerUrl }
}
