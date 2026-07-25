import { expect, test } from '@playwright/test'

test('new user can register and upload a resume', async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`

  await page.goto('/login')
  await page.getByRole('button', { name: '没有账号，创建一个' }).click()
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill('password123')
  await page.getByLabel('昵称').fill('E2E')
  await page.getByRole('button', { name: '注册并登录' }).click()

  await expect(page.getByRole('heading', { name: '求职训练工作台' })).toBeVisible()
  await page.getByLabel('简历名称').fill('E2E 后端简历')
  await page.getByLabel('粘贴文本').fill(
    '姓名：E2E\\n求职意向：后端开发工程师\\n项目经历：负责 FastAPI 接口、数据库设计和面试报告生成。',
  )
  await page.getByRole('button', { name: '上传并解析' }).click()

  await expect(page.getByRole('heading', { name: 'E2E 后端简历' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始面试' })).toBeVisible()
})
