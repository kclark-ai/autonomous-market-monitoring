import Head from 'next/head';

export default function Home() {
  return (
    <div className="min-h-screen bg-white text-black font-sans">
      <Head>
        <title>Kevin Clark | Building AI Startups with Agents</title>
        <meta name="description" content="Kevin Clark builds and scales AI startups using autonomous agents. Explore products, projects, and opportunities." />
      </Head>

      {/* NAVIGATION */}
      <header className="bg-white shadow-md py-4 px-6 sticky top-0 z-50">
        <nav className="max-w-6xl mx-auto flex justify-between items-center">
          <div className="text-xl font-bold">Kevin Clark</div>
          <ul className="flex gap-6 text-sm font-medium text-gray-700">
            <li><a href="#products" className="hover:text-black">Products</a></li>
            <li><a href="#blog" className="hover:text-black">Blog</a></li>
            <li><a href="#about" className="hover:text-black">About</a></li>
            <li><a href="#contact" className="hover:text-black">Contact</a></li>
          </ul>
        </nav>
      </header>

      {/* HERO SECTION */}
      <section className="py-20 px-4 text-center bg-gray-100">
        <h1 className="text-5xl font-bold mb-4">AI Startups. No Employees. Just Agents.</h1>
        <p className="text-lg mb-6">Kevin Clark builds AI companies powered entirely by autonomous agents. Welcome to the future of entrepreneurship.</p>
        <div className="flex justify-center gap-4">
          <a href="#products" className="bg-black text-white px-6 py-3 rounded-md">Explore Products</a>
          <a href="#contact" className="border border-black px-6 py-3 rounded-md">Get in Touch</a>
        </div>
      </section>

      {/* METRICS */}
      <section className="py-16 px-4 bg-white text-center">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-4xl mx-auto">
          <div>
            <h2 className="text-4xl font-bold">15+</h2>
            <p className="text-gray-700">Years in Consulting</p>
          </div>
          <div>
            <h2 className="text-4xl font-bold">50+</h2>
            <p className="text-gray-700">Fortune 500 Clients</p>
          </div>
          <div>
            <h2 className="text-4xl font-bold">1st</h2>
            <p className="text-gray-700">Agent-Powered Startup Studio</p>
          </div>
        </div>
      </section>

      {/* PRODUCT SHOWCASE */}
      <section id="products" className="py-20 px-4 bg-gray-50">
        <h2 className="text-3xl font-bold text-center mb-12">AI Products</h2>
        <div className="max-w-3xl mx-auto bg-white shadow rounded p-6">
          <h3 className="text-xl font-semibold mb-2">🧠 TrendScout</h3>
          <p className="mb-4">A daily AI trends radar. Automatically curates the newest tools, launches, and ideas from the AI frontier.</p>
          <a href="#" className="text-blue-600 font-semibold">View Demo →</a>
        </div>
      </section>

      {/* BLOG SECTION */}
      <section id="blog" className="py-20 px-4 bg-white">
        <h2 className="text-3xl font-bold text-center mb-12">From the Blog</h2>
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="border p-4 rounded shadow-sm">
            <h4 className="text-lg font-bold mb-2">Building AI Companies with Agents</h4>
            <p className="text-gray-600 text-sm">How I use CrewAI to simulate an entire startup team...</p>
          </div>
          <div className="border p-4 rounded shadow-sm">
            <h4 className="text-lg font-bold mb-2">Why TrendScout Exists</h4>
            <p className="text-gray-600 text-sm">Most AI tools are hype. TrendScout filters signal from noise...</p>
          </div>
          <div className="border p-4 rounded shadow-sm">
            <h4 className="text-lg font-bold mb-2">The Future is Agent-Led</h4>
            <p className="text-gray-600 text-sm">My vision of business automation in 2030...</p>
          </div>
        </div>
      </section>

      {/* ABOUT SECTION */}
      <section id="about" className="py-20 px-4 bg-gray-100 text-center">
        <h2 className="text-3xl font-bold mb-4">About Kevin Clark</h2>
        <p className="max-w-3xl mx-auto text-gray-700">After 15+ years consulting Fortune 500s and building trust across industries, I became obsessed with one thing: building entire companies with autonomous AI agents. kevinclark.ai is the first public lab showing that future in motion.</p>
      </section>

      {/* EMAIL SIGNUP */}
      <section className="py-20 px-4 bg-white text-center">
        <h2 className="text-2xl font-semibold mb-4">Get Updates</h2>
        <p className="text-gray-600 mb-6">Join the mailing list to get updates about products, tools, and experiments.</p>
        <form className="max-w-md mx-auto flex gap-2">
          <input type="email" placeholder="you@example.com" className="flex-1 border px-4 py-2 rounded" />
          <button className="bg-black text-white px-4 py-2 rounded">Subscribe</button>
        </form>
      </section>

      {/* CONTACT */}
      <section id="contact" className="py-20 px-4 bg-white text-center">
        <h2 className="text-3xl font-bold mb-4">Let's Connect</h2>
        <p className="mb-6">Have an idea, collaboration, or press inquiry? Reach out below.</p>
        <form className="max-w-xl mx-auto grid gap-4">
          <input type="text" placeholder="Your Name" className="border px-4 py-2 rounded w-full" />
          <input type="email" placeholder="Your Email" className="border px-4 py-2 rounded w-full" />
          <textarea placeholder="Your Message" className="border px-4 py-2 rounded w-full h-32" />
          <button type="submit" className="bg-black text-white px-6 py-3 rounded">Send Message</button>
        </form>
      </section>

      {/* FOOTER */}
      <footer className="bg-gray-100 py-8 text-center text-sm text-gray-600">
        <p>© 2025 Kevin Clark. All rights reserved.</p>
        <div className="flex justify-center gap-4 mt-4">
          <a href="#" className="hover:text-black">Twitter</a>
          <a href="#" className="hover:text-black">LinkedIn</a>
          <a href="#" className="hover:text-black">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
