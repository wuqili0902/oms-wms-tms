export function lazyLoadWithRetry(
  loader: () => Promise<any>,
  retries = 2,
  delay = 1000,
): () => Promise<any> {
  return () =>
    new Promise((resolve, reject) => {
      const attempt = (n: number) => {
        loader()
          .then(resolve)
          .catch((err: unknown) => {
            if (n <= 0) {
              reject(err)
              return
            }
            setTimeout(() => attempt(n - 1), delay)
          })
      }
      attempt(retries)
    })
}
