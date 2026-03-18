import App from './App.svelte'
import './lib/styles.css'

const target = document.getElementById('app')

if (!target) {
  throw new Error('App target #app was not found.')
}

new App({
  target,
})
