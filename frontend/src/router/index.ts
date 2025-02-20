import { createRouter, createWebHashHistory } from 'vue-router'


const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('@/views/ConfigView.vue'),
    },
    {
      path: '/player',
      name: 'player',
      component: () => import('@/views/PlayerView.vue'),
    },
    {
      path: '/playlist',
      name: 'playlist',
      component: () => import('@/views/PlaylistControlView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/PlayHistoryView.vue'),
    },
    {
      path: '/query-history',
      name: 'query-history',
      component: () => import('@/views/QueryHistoryView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/config',
    }
  ]
})

export default router
