import { expect, test } from '@playwright/test'


test('user can generate and execute a basic weekly training plan', async ({ page }) => {
  const email = `training-plan-${Date.now()}@example.com`

  await page.goto('/login')
  await page.getByRole('button', { name: '没有账号，创建一个' }).click()
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill('password123')
  await page.getByLabel('昵称').fill('Training Plan')
  await page.getByRole('button', { name: '注册并登录' }).click()
  await expect(page.getByRole('heading', { name: '求职训练工作台' })).toBeVisible()

  await page.goto('/training-plan')
  await expect(page.getByTestId('training-plan-page')).toBeVisible()
  await expect(page.getByText('本周还没有训练计划')).toBeVisible()
  await page.getByRole('button', { name: '生成本周计划' }).click()

  await expect(page.getByText('完成进度')).toBeVisible()
  await expect(page.getByText('错题复习').first()).toBeVisible()
  await expect(page.getByText('模拟面试').first()).toBeVisible()
  await expect(page.getByText('项目复盘').first()).toBeVisible()

  await page.getByRole('button', { name: '完成' }).first().click()
  await expect(page.getByText('已完成').first()).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: '本周训练计划' })).toBeVisible()
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(hasHorizontalOverflow).toBeFalsy()
})
